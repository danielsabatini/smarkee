"""Adaptadores do NATS JetStream do Manager: consumers de trabalho e de persistência.

Regras (`docs/NATS.md`): o Manager não publica (o Publisher do tipo publica o outbox). O consumer de
trabalho é **durável e compartilhado** (pull), declarado pela infraestrutura, com ACK explícito
**depois** da gravação durável; falha transitória volta à fila com atraso (`nak`); mensagem
inválida é retirada do fluxo (`term`) e registrada.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any, Protocol

import psycopg
import psycopg_pool
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from core_account.common.messaging import consume
from core_account.manager.domain.errors import PermanentMessageError
from core_account.manager.domain.kind import ResourceKind
from core_account.manager.domain.outcome import Outcome
from core_account.manager.handlers.observed import ObservedHandler
from core_account.manager.handlers.ports import Store
from core_account.manager.handlers.requested import RequestedHandler
from core_account.manager.handlers.result import ResultHandler
from core_account.manager.store.ssot import SsotStore
from core_account.manager.store.tables import tables_of

logger = logging.getLogger(__name__)

REQUESTED_STREAM = "REQUESTED"
OBSERVED_STREAM = "OBSERVED"
RESULT_STREAM = "RESULT"
TRANSIENT_RETRY_DELAYS_SECONDS = (0.1, 0.5, 1.0)
REDELIVERY_DELAY_SECONDS = 5.0

TRANSIENT_DATABASE_ERRORS = (
    psycopg.errors.LockNotAvailable,  # lock_timeout (55P03)
    psycopg.errors.DeadlockDetected,  # 40P01
    psycopg.errors.SerializationFailure,  # 40001
    psycopg.OperationalError,  # conexão perdida, statement_timeout, falha de rede
    psycopg_pool.PoolTimeout,
)


class Disposition(StrEnum):
    ACK = "ack"
    TERM = "term"
    RETRY = "retry"


class MessageHandler(Protocol):
    """Aplica uma mensagem consumida ao SSOT de um tipo, em uma unidade atômica."""

    async def handle(
        self, store: Store, kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> Outcome: ...


async def apply_message(
    pool: psycopg_pool.AsyncConnectionPool[Any],
    handler: MessageHandler,
    kind: ResourceKind,
    data: bytes,
) -> Disposition:
    """Aplica uma mensagem e decide o que fazer com ela no transporte (ACK, TERM ou RETRY)."""
    try:
        message: Mapping[str, Any] = json.loads(data)
    except ValueError:
        logger.error("message is not valid JSON")
        return Disposition.TERM
    for attempt, delay in enumerate((*TRANSIENT_RETRY_DELAYS_SECONDS, None)):
        try:
            async with pool.connection() as connection:
                await handler.handle(
                    SsotStore(connection, tables_of(kind.resource_type)), kind, message
                )
            return Disposition.ACK
        except PermanentMessageError as error:
            logger.error(
                "message rejected as permanently invalid",
                extra={"smarkee.reason": str(error)},
            )
            return Disposition.TERM
        except TRANSIENT_DATABASE_ERRORS as error:
            logger.warning(
                "transient database error while handling a message",
                extra={"smarkee.delivery.attempt": attempt + 1},
                exc_info=error,
            )
            if delay is None:
                return Disposition.RETRY
            await asyncio.sleep(delay)
    return Disposition.RETRY  # inalcançável; mantém o tipo de retorno explícito


class StreamConsumer:
    """Consumer de trabalho ou de persistência do Manager, durável e compartilhado (`NATS.md` §7.3).

    Um consumer por Stream que o Manager lê, com filtro único do tipo, declarado pela
    infraestrutura.
    """

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        kind: ResourceKind,
        handler: MessageHandler,
        *,
        stream: str,
        name_suffix: str,
        batch_size: int = 10,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._on_cycle = on_cycle
        self._jetstream = jetstream
        self._pool = pool
        self._kind = kind
        self._handler = handler
        self._stream = stream
        self._name_suffix = name_suffix
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds

    @property
    def durable_name(self) -> str:
        return f"core-{self._kind.resource_type}-manager-{self._name_suffix}"

    async def run(self, stop: asyncio.Event) -> None:
        subscription = await self._jetstream.pull_subscribe_bind(
            consumer=self.durable_name, stream=self._stream
        )
        await consume(
            subscription,
            self._dispose,
            stop,
            batch_size=self._batch_size,
            fetch_timeout_seconds=self._fetch_timeout,
            on_cycle=self._on_cycle,
        )

    async def _dispose(self, message: Msg) -> None:
        disposition = await apply_message(self._pool, self._handler, self._kind, message.data)
        logger.debug(
            "message handled",
            extra={
                "messaging.consumer.group.name": self.durable_name,
                "smarkee.outcome": disposition.value,
            },
        )
        match disposition:
            case Disposition.ACK:
                await message.ack()
            case Disposition.TERM:
                await message.term()
            case Disposition.RETRY:
                await message.nak(delay=REDELIVERY_DELAY_SECONDS)


class RequestedConsumer(StreamConsumer):
    """Consumer de `requested` do tipo (trabalho)."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        kind: ResourceKind,
        *,
        handler: RequestedHandler | None = None,
        batch_size: int = 10,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(
            jetstream,
            pool,
            kind,
            handler or RequestedHandler(),
            stream=REQUESTED_STREAM,
            name_suffix="requested",
            batch_size=batch_size,
            fetch_timeout_seconds=fetch_timeout_seconds,
            on_cycle=on_cycle,
        )


class ObservedConsumer(StreamConsumer):
    """Consumer de `observed` do tipo (persistência)."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        kind: ResourceKind,
        *,
        handler: ObservedHandler | None = None,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(
            jetstream,
            pool,
            kind,
            handler or ObservedHandler(),
            stream=OBSERVED_STREAM,
            name_suffix="observed",
            fetch_timeout_seconds=fetch_timeout_seconds,
            on_cycle=on_cycle,
        )


class ResultConsumer(StreamConsumer):
    """Consumer de `completed` e `failed` do tipo (persistência)."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        kind: ResourceKind,
        *,
        handler: ResultHandler | None = None,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(
            jetstream,
            pool,
            kind,
            handler or ResultHandler(),
            stream=RESULT_STREAM,
            name_suffix="result",
            fetch_timeout_seconds=fetch_timeout_seconds,
            on_cycle=on_cycle,
        )
