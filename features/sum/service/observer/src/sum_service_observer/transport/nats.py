"""Adaptadores do NATS JetStream do Observer (`docs/NATS.md` §7.4).

Estado em memória exige **um consumer por instância**, com `DeliverLastPerSubject`, nome único por
execução do processo e `inactive_threshold`: assim cada instância reconstrói o que precisa observar
(último `desired` de cada recurso) a partir da mensageria.
"""

import asyncio
import logging
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

from sum_service_observer.engine.observer import PublishError

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 5.0
REDELIVERY_DELAY_SECONDS = 5.0
STREAMS = (
    ("DESIRED", "manager.desired.sum.service.>", "desired"),
    ("RESULT", "executor.*.sum.service.>", "result"),
)


async def connect(
    url: str, user: str, password: SecretStr | None, *, name: str = "sum-service-observer"
) -> NatsClient:
    """Conecta com a identidade do Observer (`sum-service-observer`)."""
    secret = password.get_secret_value() if password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    options: dict[str, Any] = {"servers": [url], "user": user, "password": secret, "name": name}
    return await nats.connect(**options)  # pyright: ignore[reportUnknownMemberType]


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica um `observed` e espera a confirmação, com `Nats-Msg-Id` igual ao `messageId`."""

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        try:
            await self._jetstream.publish(
                subject,
                payload,
                timeout=PUBLISH_TIMEOUT_SECONDS,
                headers={"Nats-Msg-Id": message_id},
            )
        except (nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError) as error:
            raise PublishError(type(error).__name__) from error


class StateConsumer:
    """Consumer de estado de uma instância do Observer para um Stream."""

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
        self._durable = f"sum-service-observer-{name_suffix}-{instance}"
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
                logger.warning("fetch failed", extra={"error_type": type(error).__name__})
                await asyncio.sleep(1.0)
                continue
            for message in messages:
                await self._settle(message)

    async def _settle(self, message: Msg) -> None:
        try:
            await self._handle(message.data)
        except Exception as error:  # um erro de processamento volta à fila; nunca derruba o laço
            logger.error(
                "message processing failed; it will be redelivered",
                extra={"consumer": self._durable, "error_type": type(error).__name__},
            )
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
            return
        await message.ack()


def new_instance_name() -> str:
    """Único por execução do processo: o consumer da instância não reaproveita posição antiga."""
    return uuid.uuid4().hex[:8]
