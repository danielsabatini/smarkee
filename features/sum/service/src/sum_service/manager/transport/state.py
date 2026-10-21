"""Consumo de `observed` e de resultados pelo Manager (`docs/NATS.md` §7.3; decisões 0033 e 0080).

Mesmo contrato do consumo de `requested`: a mensagem é confirmada depois da gravação. Erro
transitório do banco volta à fila; mensagem fora do contrato é retirada do fluxo (`term`).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

import psycopg
import psycopg_pool
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from sum_service.common.contracts.envelope import EnvelopeError, read_envelope
from sum_service.common.messaging import consume
from sum_service.manager.domain.errors import PermanentMessageError
from sum_service.manager.domain.kind import SERVICE, ResourceKind
from sum_service.manager.domain.outcome import Outcome
from sum_service.manager.handlers.account_removed import remove_links_of
from sum_service.manager.handlers.ports import Store
from sum_service.manager.store.state import StateStore
from sum_service.manager.transport.requested import TRANSIENT_DATABASE_ERRORS, Disposition

logger = logging.getLogger(__name__)
REDELIVERY_DELAY_SECONDS = 5.0


def parse_account_removed(data: bytes) -> str | None:
    """`resourceId` da conta removida, ou `None` se o `updated` não é de remoção (a ignorar)."""
    try:
        envelope = read_envelope(data)
    except EnvelopeError as error:
        raise PermanentMessageError(error.reason) from None
    if envelope.module != "core" or envelope.resource_type != "account":
        raise PermanentMessageError("mensagem de outro tipo ou módulo")
    if envelope.message_type.value != "updated":
        raise PermanentMessageError("tipo de mensagem inesperado")
    return envelope.resource_id if envelope.data.get("removed") is True else None


class StateHandler(Protocol):
    """Handler do template para `observed` e resultados (perfil `manager-handlers`, 0080)."""

    async def handle(
        self, store: Store, kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> Outcome: ...


async def process_state(
    pool: psycopg_pool.AsyncConnectionPool[Any], handler: StateHandler, data: bytes
) -> Disposition:
    """Aplica um `observed` ou um resultado; o handler abre a própria transação."""
    try:
        message: Mapping[str, Any] = json.loads(data)
    except ValueError:
        logger.error("state message is not valid JSON")
        return Disposition.TERM
    for attempt, delay in enumerate((0.1, 0.5, 1.0, None)):
        try:
            async with pool.connection() as connection:
                await handler.handle(StateStore(connection), SERVICE, message)
            return Disposition.ACK
        except PermanentMessageError as error:
            logger.error(
                "state message rejected as permanently invalid",
                extra={"smarkee.reason": str(error)},
            )
            return Disposition.TERM
        except TRANSIENT_DATABASE_ERRORS as error:
            logger.warning(
                "transient database error while applying a state message",
                extra={"smarkee.delivery.attempt": attempt + 1},
                exc_info=error,
            )
            if delay is None:
                return Disposition.RETRY
            await asyncio.sleep(delay)
    return Disposition.RETRY


async def process_account_removed(
    pool: psycopg_pool.AsyncConnectionPool[Any], data: bytes
) -> Disposition:
    return await _process(pool, lambda conn: _account_removed(conn, data))


async def _account_removed(conn: psycopg.AsyncConnection[Any], data: bytes) -> None:
    account_id = parse_account_removed(data)
    if account_id is None:
        return  # `updated` comum da conta: nada a fazer
    removed = await remove_links_of(conn, account_id)
    logger.info(
        "links of a removed account deleted",
        extra={"smarkee.account.id": account_id, "smarkee.links.removed": removed},
    )


async def _process(
    pool: psycopg_pool.AsyncConnectionPool[Any],
    apply: Callable[[psycopg.AsyncConnection[Any]], Awaitable[None]],
) -> Disposition:
    for attempt, delay in enumerate((0.1, 0.5, 1.0, None)):
        try:
            async with pool.connection() as connection, connection.transaction():
                await apply(connection)
            return Disposition.ACK
        except PermanentMessageError as error:
            logger.error(
                "state message rejected as permanently invalid",
                extra={"smarkee.reason": str(error)},
            )
            return Disposition.TERM
        except TRANSIENT_DATABASE_ERRORS as error:
            logger.warning(
                "transient database error while applying a state message",
                extra={"smarkee.delivery.attempt": attempt + 1},
                exc_info=error,
            )
            if delay is None:
                return Disposition.RETRY
            await asyncio.sleep(delay)
    return Disposition.RETRY


async def run_consumer(
    jetstream: JetStreamContext,
    *,
    stream: str,
    durable: str,
    handle: Callable[[bytes], Awaitable[Disposition]],
    stop: asyncio.Event,
    on_cycle: Callable[[], None] = lambda: None,
    batch_size: int = 10,
    fetch_timeout_seconds: float = 2.0,
) -> None:
    """Laço de um consumer durável: confirma (ACK), retira (TERM) ou devolve à fila (NAK) cada
    mensagem."""
    subscription = await jetstream.pull_subscribe_bind(consumer=durable, stream=stream)

    async def settle(message: Msg) -> None:
        await _settle(message, handle)

    await consume(
        subscription,
        settle,
        stop,
        batch_size=batch_size,
        fetch_timeout_seconds=fetch_timeout_seconds,
        on_cycle=on_cycle,
    )


async def _settle(message: Msg, handle: Callable[[bytes], Awaitable[Disposition]]) -> None:
    disposition = await handle(message.data)
    logger.info("message handled", extra={"smarkee.outcome": disposition.value})
    match disposition:
        case Disposition.ACK:
            await message.ack()
        case Disposition.TERM:
            await message.term()
        case Disposition.RETRY:
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
