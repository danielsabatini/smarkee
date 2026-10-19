"""Adaptadores comuns do NATS JetStream (`docs/NATS.md`).

Conexão com a identidade do papel, publicação com deduplicação pelo `messageId` e o laço de
consumo por *pull*. As regras de negócio de cada papel ficam nos seus pacotes.
"""

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Generator
from typing import Protocol

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as MessagingClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from sum_service.common.logging_config import (
    TRACEPARENT_HEADER,
    bind_message_context,
    bind_traceparent,
    current_traceparent,
)
from sum_service.common.ports import PublishError
from sum_service.common.settings import MessagingSettings

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 5.0
FETCH_ERROR_PAUSE_SECONDS = 1.0
REDELIVERY_DELAY_SECONDS = 5.0

# Recusas que repetir não resolve: a mensagem nunca será aceita como está.
_PERMANENT_ERRORS = (nats.errors.MaxPayloadError, nats.js.errors.BadRequestError)


async def connect(settings: MessagingSettings, *, name: str) -> MessagingClient:
    """Conecta com a identidade do papel (`name`, por exemplo `sum-service-manager`)."""
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def stream_of(client: MessagingClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class StreamPublisher:
    """Publica no JetStream e espera a confirmação, com deduplicação pelo `messageId`.

    O `traceparent` corrente, se houver, vai no header NATS de mesmo nome, sem alteração
    (decisão 0055); ele não faz parte do envelope.
    """

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        headers = {"Nats-Msg-Id": message_id}
        traceparent = current_traceparent()
        if traceparent is not None:
            headers[TRACEPARENT_HEADER] = traceparent
        try:
            await self._jetstream.publish(
                subject, payload, timeout=PUBLISH_TIMEOUT_SECONDS, headers=headers
            )
        except (nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError) as error:
            # Stream cheio (`DiscardNew`), sem resposta ou indisponível: falha repetível.
            raise PublishError(
                type(error).__name__, permanent=isinstance(error, _PERMANENT_ERRORS)
            ) from error


@contextlib.contextmanager
def message_scope(message: Msg) -> Generator[None]:
    """Liga à mensagem o contexto de trace e de negócio dos logs, e o desliga ao final.

    O `traceparent` vem no header NATS (decisão 0055); sem ele, segue sem trace. O contexto vale
    só para esta mensagem.
    """
    bind_traceparent((message.headers or {}).get(TRACEPARENT_HEADER))
    bind_message_context(message.data)
    try:
        yield
    finally:
        bind_traceparent(None)


async def consume(
    subscription: JetStreamContext.PullSubscription,
    settle: Callable[[Msg], Awaitable[None]],
    stop: asyncio.Event,
    *,
    batch_size: int,
    fetch_timeout_seconds: float = 2.0,
    on_cycle: Callable[[], None] = lambda: None,
    with_trace: bool = True,
) -> None:
    """Busca mensagens em lotes até `stop` e entrega cada uma a `settle` (que dá o ACK).

    `on_cycle` é o sinal de vida do laço (liveness). Uma falha de busca é registrada e o laço
    segue após uma pausa. `with_trace=False` não liga o trace da mensagem aos logs: é o caso do
    Observer, cujas observações são periódicas e não consequência de uma requisição.

    Ao terminar, cancela a assinatura: com ela ativa, o `drain()` da conexão espera o tempo limite
    inteiro (30 s) e o processo seria encerrado à força. O consumer durável continua no servidor.
    """
    try:
        while not stop.is_set():
            on_cycle()
            try:
                messages = await subscription.fetch(batch_size, timeout=fetch_timeout_seconds)
            except TimeoutError:
                continue
            except (nats.errors.Error, nats.js.errors.Error) as error:
                logger.warning("fetch failed", exc_info=error)
                await asyncio.sleep(FETCH_ERROR_PAUSE_SECONDS)
                continue
            for message in messages:
                if with_trace:
                    with message_scope(message):
                        await settle(message)
                else:
                    await settle(message)
    finally:
        with contextlib.suppress(nats.errors.Error, nats.js.errors.Error):
            await subscription.unsubscribe()


def new_instance_name() -> str:
    """Único por execução do processo: o consumer da instância não reaproveita posição antiga."""
    return uuid.uuid4().hex[:8]


class MessageSink(Protocol):
    """Quem reage às mensagens de estado (o motor do Reconciler ou do Observer)."""

    async def on_message(self, data: bytes) -> object: ...


class StateConsumer:
    """Consumer de estado de uma instância, para um Stream (`docs/NATS.md` §7.4, §7.6).

    Estado em memória exige **um consumer por instância**, com `DeliverLastPerSubject`, nome único
    por execução do processo e `inactive_threshold`: assim cada instância reconstrói o estado
    completo (último `desired`, `observed` e resultado de cada recurso) a partir da mensageria.
    """

    def __init__(
        self,
        jetstream: JetStreamContext,
        sink: MessageSink,
        *,
        durable: str,
        stream: str,
        filter_subject: str,
        inactive_threshold_seconds: int,
        traced: bool,
        batch_size: int = 50,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._jetstream = jetstream
        self._sink = sink
        self._durable = durable
        self._stream = stream
        self._filter = filter_subject
        self._inactive = float(inactive_threshold_seconds)
        self._traced = traced
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds
        self._on_cycle = on_cycle

    async def run(self, stop: asyncio.Event) -> None:
        subscription = await self._jetstream.pull_subscribe(
            self._filter,
            durable=self._durable,
            stream=self._stream,
            config=ConsumerConfig(
                deliver_policy=DeliverPolicy.LAST_PER_SUBJECT,
                ack_policy=AckPolicy.EXPLICIT,
                filter_subject=self._filter,
                inactive_threshold=self._inactive,
            ),
        )
        await consume(
            subscription,
            self._settle,
            stop,
            batch_size=self._batch_size,
            fetch_timeout_seconds=self._fetch_timeout,
            on_cycle=self._on_cycle,
            with_trace=self._traced,
        )

    async def _settle(self, message: Msg) -> None:
        try:
            await self._sink.on_message(message.data)
        except Exception as error:  # um erro de processamento volta à fila; nunca derruba o laço
            logger.error(
                "message processing failed; it will be redelivered",
                extra={"messaging.consumer.group.name": self._durable},
                exc_info=error,
            )
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
            return
        await message.ack()
        if self._traced:
            logger.info(
                "message handled",
                extra={
                    "messaging.consumer.group.name": self._durable,
                    "smarkee.outcome": "acknowledged",
                },
            )
