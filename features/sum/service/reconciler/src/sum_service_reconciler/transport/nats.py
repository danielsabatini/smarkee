"""Adaptadores do NATS JetStream do Reconciler (`docs/NATS.md` §7.4).

Estado em memória exige **um consumer por instância**, com `DeliverLastPerSubject`, nome único por
execução do processo e `inactive_threshold`: assim cada instância reconstrói o estado completo
(último `desired`, `observed` e resultado de cada recurso) a partir da mensageria.
"""

import asyncio
import logging
import random
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from pydantic import SecretStr

from sum_service_reconciler.engine.reconciler import PublishError, Reconciler
from sum_service_reconciler.logging_config import (
    TRACEPARENT_HEADER,
    bind_message_context,
    bind_traceparent,
    current_traceparent,
)
from sum_service_reconciler.settings import LoopSettings

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 5.0
REDELIVERY_DELAY_SECONDS = 5.0
STREAMS = (
    ("DESIRED", "manager.desired.sum.service.>", "desired"),
    ("OBSERVED", "observer.observed.sum.service.>", "observed"),
    ("RESULT", "executor.*.sum.service.>", "result"),
)
_PERMANENT_ERRORS = (nats.errors.MaxPayloadError, nats.js.errors.BadRequestError)


async def connect(
    url: str, user: str, password: SecretStr | None, *, name: str = "sum-service-reconciler"
) -> NatsClient:
    """Conecta com a identidade do Reconciler (`sum-service-reconciler`)."""
    secret = password.get_secret_value() if password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    options: dict[str, Any] = {"servers": [url], "user": user, "password": secret, "name": name}
    return await nats.connect(**options)  # pyright: ignore[reportUnknownMemberType]


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica uma `action` e espera a confirmação, com `Nats-Msg-Id` igual ao `actionId`."""

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
            raise PublishError(type(error).__name__) from error


class StateConsumer:
    """Consumer de estado de uma instância do Reconciler para um Stream."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        handle: Callable[[bytes], Awaitable[object]],
        *,
        stream: str,
        filter_subject: str,
        name_suffix: str,
        instance: str,
        inactive_threshold_seconds: int,
        batch_size: int = 50,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._jetstream = jetstream
        self._handle = handle
        self._stream = stream
        self._filter = filter_subject
        self._durable = f"sum-service-reconciler-{name_suffix}-{instance}"
        self._inactive = float(inactive_threshold_seconds)
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds
        self._on_cycle = on_cycle

    @property
    def consumer_name(self) -> str:
        return self._durable

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
        while not stop.is_set():
            self._on_cycle()  # sinal de vida do laço (liveness)
            try:
                messages = await subscription.fetch(self._batch_size, timeout=self._fetch_timeout)
            except TimeoutError:
                continue
            except (nats.errors.Error, nats.js.errors.Error) as error:
                logger.warning("fetch failed", exc_info=error)
                await asyncio.sleep(1.0)
                continue
            for message in messages:
                await self._settle(message)

    async def _settle(self, message: Msg) -> None:
        # O contexto de trace vem no header NATS (decisão 0055); vale só para esta mensagem.
        bind_traceparent((message.headers or {}).get(TRACEPARENT_HEADER))
        bind_message_context(message.data)
        try:
            await self._settle_bound(message)
        finally:
            bind_traceparent(None)

    async def _settle_bound(self, message: Msg) -> None:
        try:
            await self._handle(message.data)
        except Exception as error:  # um erro de processamento volta à fila; nunca derruba o laço
            logger.error(
                "message processing failed; it will be redelivered",
                extra={"messaging.consumer.group.name": self._durable},
                exc_info=error,
            )
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
            return
        await message.ack()
        logger.info(
            "message handled",
            extra={
                "messaging.consumer.group.name": self._durable,
                "smarkee.outcome": "acknowledged",
            },
        )


async def periodic_reevaluation(
    reconciler: Reconciler,
    settings: LoopSettings,
    stop: asyncio.Event,
    on_cycle: Callable[[], None] = lambda: None,
) -> None:
    """Reavalia todos os recursos de tempos em tempos, com jitter (`LOOP.md` §25)."""
    while not stop.is_set():
        on_cycle()
        jitter = 1 + random.uniform(-settings.reevaluation_jitter, settings.reevaluation_jitter)  # noqa: S311 (jitter, não criptografia)
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.reevaluation_interval_seconds * jitter
            )
        except TimeoutError:
            await reconciler.evaluate_all()


def new_instance_name() -> str:
    """Único por execução do processo: o consumer da instância não reaproveita posição antiga."""
    return uuid.uuid4().hex[:8]
