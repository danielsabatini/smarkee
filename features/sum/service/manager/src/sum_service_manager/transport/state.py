"""Consumo de `observed` e de resultados pelo Manager (`docs/NATS.md` §7.3; decisão 0033).

Mesmo contrato do consumo de `requested`: a mensagem é confirmada depois da gravação. Erro
transitório do banco volta à fila; mensagem fora do contrato é retirada do fluxo (`term`).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import nats.errors
import nats.js.errors
import psycopg
import psycopg_pool
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from pydantic import ValidationError

from sum_service_manager.contracts import generated
from sum_service_manager.contracts.base import supports_major, validate_tolerant
from sum_service_manager.domain.errors import PermanentMessageError
from sum_service_manager.handlers.account_removed import remove_links_of
from sum_service_manager.handlers.state import (
    ObservedMessage,
    ResultMessage,
    apply_observed,
    apply_result,
)
from sum_service_manager.logging_config import (
    TRACEPARENT_HEADER,
    bind_message_context,
    bind_traceparent,
)
from sum_service_manager.transport.requested import TRANSIENT_DATABASE_ERRORS, Disposition

logger = logging.getLogger(__name__)
REDELIVERY_DELAY_SECONDS = 5.0
MODULE = "sum"
RESOURCE_TYPE = "service"


def parse_observed(data: bytes) -> ObservedMessage:
    envelope = _envelope(data, "observed")
    if envelope.presence is None or envelope.observed_at is None:
        raise PermanentMessageError("observed sem presence ou observedAt")
    roles: object = envelope.data.get("serviceRoles", [])
    if not isinstance(roles, list):
        raise PermanentMessageError("observed com serviceRoles inválido")
    items = cast("list[object]", roles)
    return ObservedMessage(
        message_id=envelope.message_id,
        resource_id=envelope.resource_id,
        presence=envelope.presence.value,
        observed_at=envelope.observed_at,
        service_roles=tuple(str(role) for role in items),
    )


def parse_result(data: bytes, outcome: str) -> ResultMessage:
    envelope = _envelope(data, outcome)
    if envelope.action_id is None or envelope.desired_generation is None:
        raise PermanentMessageError("resultado sem actionId ou desiredGeneration")
    return ResultMessage(
        message_id=envelope.message_id,
        resource_id=envelope.resource_id,
        action_id=envelope.action_id,
        desired_generation=envelope.desired_generation,
        outcome=outcome,
    )


def parse_account_removed(data: bytes) -> str | None:
    """`resourceId` da conta removida, ou `None` se o `updated` não é de remoção (a ignorar)."""
    try:
        document: Any = json.loads(data)
    except ValueError:
        raise PermanentMessageError("mensagem não é JSON") from None
    try:
        envelope = validate_tolerant(generated.MessageEnvelope, document)
    except ValidationError:
        raise PermanentMessageError("envelope fora do contrato") from None
    if not supports_major(envelope.schema_version):
        raise PermanentMessageError("schemaVersion MAJOR não suportado")
    if envelope.module != "core" or envelope.resource_type != "account":
        raise PermanentMessageError("mensagem de outro tipo ou módulo")
    if envelope.message_type.value != "updated":
        raise PermanentMessageError("tipo de mensagem inesperado")
    return envelope.resource_id if envelope.data.get("removed") is True else None


def _envelope(data: bytes, expected: str) -> generated.MessageEnvelope:
    try:
        document: Any = json.loads(data)
    except ValueError:
        raise PermanentMessageError("mensagem não é JSON") from None
    try:
        envelope = validate_tolerant(generated.MessageEnvelope, document)
    except ValidationError:
        raise PermanentMessageError("envelope fora do contrato") from None
    if not supports_major(envelope.schema_version):
        raise PermanentMessageError("schemaVersion MAJOR não suportado")
    if envelope.module != MODULE or envelope.resource_type != RESOURCE_TYPE:
        raise PermanentMessageError("mensagem de outro tipo ou módulo")
    if envelope.message_type.value != expected:
        raise PermanentMessageError("tipo de mensagem inesperado")
    return envelope


async def process_observed(pool: psycopg_pool.AsyncConnectionPool[Any], data: bytes) -> Disposition:
    return await _process(pool, lambda conn: _observed(conn, data))


async def process_result(
    pool: psycopg_pool.AsyncConnectionPool[Any], data: bytes, outcome: str
) -> Disposition:
    return await _process(pool, lambda conn: _result(conn, data, outcome))


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


async def _observed(conn: psycopg.AsyncConnection[Any], data: bytes) -> None:
    await apply_observed(conn, parse_observed(data))


async def _result(conn: psycopg.AsyncConnection[Any], data: bytes, outcome: str) -> None:
    await apply_result(conn, parse_result(data, outcome))


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
    while not stop.is_set():
        on_cycle()
        try:
            messages = await subscription.fetch(batch_size, timeout=fetch_timeout_seconds)
        except TimeoutError:
            continue
        except (nats.errors.Error, nats.js.errors.Error) as error:
            logger.warning("fetch failed", exc_info=error)
            await asyncio.sleep(1.0)
            continue
        for message in messages:
            await _settle(message, handle)


async def _settle(message: Msg, handle: Callable[[bytes], Awaitable[Disposition]]) -> None:
    # O contexto de trace vem no header NATS (decisão 0055); vale só para esta mensagem.
    bind_traceparent((message.headers or {}).get(TRACEPARENT_HEADER))
    bind_message_context(message.data)
    try:
        disposition = await handle(message.data)
        logger.info("message handled", extra={"smarkee.outcome": disposition.value})
    finally:
        bind_traceparent(None)
    match disposition:
        case Disposition.ACK:
            await message.ack()
        case Disposition.TERM:
            await message.term()
        case Disposition.RETRY:
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
