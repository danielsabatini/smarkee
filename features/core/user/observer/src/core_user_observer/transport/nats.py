"""Adaptadores do NATS JetStream do Observer (`docs/NATS.md` §7.4, §7.6).

Estado em memória exige **um consumer por instância**, com `DeliverLastPerSubject`, nome único por
execução do processo e `inactive_threshold`: assim cada instância reconstrói o estado completo
(último `desired`, `observed` e resultado de cada recurso) a partir da mensageria.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from core_user_observer.engine.observer import Observer, PublishError
from core_user_observer.settings import NatsSettings

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 5.0
STREAMS = (
    ("DESIRED", "manager.desired.core.user.>", "desired"),
    ("RESULT", "executor.*.core.user.>", "result"),
)


async def connect(settings: NatsSettings, *, name: str = "srv-core-user-observer") -> NatsClient:
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica `observed` com `Nats-Msg-Id` igual ao `messageId` (deduplicação do transporte)."""

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
        observer: Observer,
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
        self._on_cycle = on_cycle
        self._jetstream = jetstream
        self._observer = observer
        self._stream = stream
        self._filter = filter_subject
        self._durable = f"core-user-observer-{name_suffix}-{instance}"
        self._inactive = float(inactive_threshold_seconds)
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds

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
                await self._observer.on_message(message.data)
                await message.ack()


def new_instance_name() -> str:
    """Único por execução do processo: o consumer da instância não reaproveita posição antiga."""
    return uuid.uuid4().hex[:8]
