"""Adaptadores do NATS JetStream do Reconciler (`docs/NATS.md` §7.4).

Estado em memória exige **um consumer por instância**, com `DeliverLastPerSubject`, nome único por
execução do processo e `inactive_threshold`: assim cada instância reconstrói o estado completo
(último `desired`, `observed` e resultado de cada recurso) a partir da mensageria.
"""

import asyncio
import logging
import random
import uuid
from collections.abc import Callable

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from ipm_organization_reconciler.engine.reconciler import PublishError, Reconciler
from ipm_organization_reconciler.settings import LoopSettings, NatsSettings

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 5.0
STREAMS = (
    ("DESIRED", "manager.desired.ipm.organization.>", "desired"),
    ("OBSERVED", "observer.observed.ipm.organization.>", "observed"),
    ("RESULT", "executor.*.ipm.organization.>", "result"),
)


async def connect(
    settings: NatsSettings, *, name: str = "ipm-organization-reconciler"
) -> NatsClient:
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica a `action` com `Nats-Msg-Id` igual ao `actionId` (deduplicação do transporte)."""

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
    """Consumer de estado de uma instância do Reconciler para um Stream."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        reconciler: Reconciler,
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
        self._reconciler = reconciler
        self._stream = stream
        self._filter = filter_subject
        self._durable = f"ipm-organization-reconciler-{name_suffix}-{instance}"
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
                await self._reconciler.on_message(message.data)
                await message.ack()


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
