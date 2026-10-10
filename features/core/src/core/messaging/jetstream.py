"""Adaptadores do NATS JetStream: conexão, publicação e consumer de trabalho do Manager.

Regras (`docs/NATS.md`): publicação com `Nats-Msg-Id` igual ao `messageId` e espera da
confirmação do servidor; consumer de trabalho **durável e compartilhado** (pull), declarado pela
infraestrutura, com ACK explícito **depois** da gravação durável; falha transitória volta à fila
com atraso (`nak`); mensagem inválida é retirada do fluxo (`term`) e registrada.
"""

import asyncio
import json
import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

import nats
import nats.errors
import nats.js.errors
import psycopg
import psycopg_pool
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from core.manager.errors import PermanentMessageError
from core.manager.kinds import ResourceKind
from core.manager.requested import RequestedHandler
from core.messaging.publisher import PublishError
from core.settings import NatsSettings

logger = logging.getLogger(__name__)

REQUESTED_STREAM = "REQUESTED"
PUBLISH_TIMEOUT_SECONDS = 5.0
TRANSIENT_RETRY_DELAYS_SECONDS = (0.1, 0.5, 1.0)
REDELIVERY_DELAY_SECONDS = 5.0

TRANSIENT_DATABASE_ERRORS = (
    psycopg.errors.LockNotAvailable,  # lock_timeout (55P03)
    psycopg.errors.DeadlockDetected,  # 40P01
    psycopg.errors.SerializationFailure,  # 40001
    psycopg.OperationalError,  # conexão perdida, statement_timeout, falha de rede
    psycopg_pool.PoolTimeout,
)


async def connect(settings: NatsSettings, *, name: str = "core") -> NatsClient:
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica no JetStream e espera a confirmação, com deduplicação pelo `messageId`."""

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
            # Stream cheio (`DiscardNew`), sem resposta ou indisponível: rejeição repetível.
            raise PublishError(type(error).__name__) from error


class Disposition(StrEnum):
    ACK = "ack"
    TERM = "term"
    RETRY = "retry"


async def process_requested(
    pool: psycopg_pool.AsyncConnectionPool[Any],
    handler: RequestedHandler,
    kind: ResourceKind,
    data: bytes,
) -> Disposition:
    """Aplica um `requested` e decide o que fazer com a mensagem no transporte."""
    try:
        message: Mapping[str, Any] = json.loads(data)
    except ValueError:
        logger.error("requested is not valid JSON", extra={"resource_type": kind.resource_type})
        return Disposition.TERM
    for attempt, delay in enumerate((*TRANSIENT_RETRY_DELAYS_SECONDS, None)):
        try:
            async with pool.connection() as connection:
                await handler.handle(connection, kind, message)
            return Disposition.ACK
        except PermanentMessageError as error:
            logger.error(
                "requested rejected as permanently invalid",
                extra={"resource_type": kind.resource_type, "reason": str(error)},
            )
            return Disposition.TERM
        except TRANSIENT_DATABASE_ERRORS as error:
            logger.warning(
                "transient database error while handling requested",
                extra={
                    "resource_type": kind.resource_type,
                    "error_type": type(error).__name__,
                    "attempt": attempt + 1,
                },
            )
            if delay is None:
                return Disposition.RETRY
            await asyncio.sleep(delay)
    return Disposition.RETRY  # inalcançável; mantém o tipo de retorno explícito


class RequestedConsumer:
    """Consumer de trabalho do Manager para `requested` de um tipo (`docs/NATS.md` §7.3)."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        kind: ResourceKind,
        *,
        handler: RequestedHandler | None = None,
        batch_size: int = 10,
        fetch_timeout_seconds: float = 2.0,
    ) -> None:
        self._jetstream = jetstream
        self._pool = pool
        self._kind = kind
        self._handler = handler or RequestedHandler()
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds

    @property
    def durable_name(self) -> str:
        return f"core-{self._kind.resource_type}-manager-requested"

    async def run(self, stop: asyncio.Event) -> None:
        subscription = await self._jetstream.pull_subscribe_bind(
            consumer=self.durable_name, stream=REQUESTED_STREAM
        )
        while not stop.is_set():
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
        disposition = await process_requested(self._pool, self._handler, self._kind, message.data)
        match disposition:
            case Disposition.ACK:
                await message.ack()
            case Disposition.TERM:
                await message.term()
            case Disposition.RETRY:
                await message.nak(delay=REDELIVERY_DELAY_SECONDS)
