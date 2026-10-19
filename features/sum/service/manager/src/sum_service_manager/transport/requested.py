"""Consumo de `requested` de `sum.service` pelo Manager (`docs/NATS.md` §7.3; decisão 0033).

O consumer de trabalho é durável e compartilhado (pull), declarado pela infraestrutura. O ACK vem
**depois** da gravação durável. Falha transitória do banco volta à fila com atraso (`nak`). Mensagem
inválida é retirada do fluxo (`term`), com o motivo no log.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

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
from sum_service_manager.handlers.requested import RequestedHandler
from sum_service_manager.logging_config import (
    TRACEPARENT_HEADER,
    bind_message_context,
    bind_traceparent,
)

logger = logging.getLogger(__name__)

REQUESTED_STREAM = "REQUESTED"
TRANSIENT_RETRY_DELAYS_SECONDS = (0.1, 0.5, 1.0)
REDELIVERY_DELAY_SECONDS = 5.0
TRANSIENT_DATABASE_ERRORS = (
    psycopg.errors.LockNotAvailable,
    psycopg.errors.DeadlockDetected,
    psycopg.errors.SerializationFailure,
    psycopg.OperationalError,
    psycopg_pool.PoolTimeout,
)


class Disposition(StrEnum):
    ACK = "ack"
    TERM = "term"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class CreateRequest:
    operation_id: str
    request_digest: str
    requested_by: str
    correlation_id: str
    requested_message_id: str
    resource_id: str
    owner_account_id: str
    service: str


@dataclass(frozen=True, slots=True)
class DeleteRequest:
    operation_id: str
    request_digest: str
    requested_by: str
    correlation_id: str
    requested_message_id: str
    resource_id: str
    expected_version: str


ParsedRequest = CreateRequest | DeleteRequest


def parse_request(data: bytes) -> ParsedRequest:
    """Valida a mensagem `requested` (envelope e dados) e a devolve pronta para o handler.

    Qualquer desvio do contrato é `PermanentMessageError`: a mensagem não será aceita como está.
    """
    try:
        document: Any = json.loads(data)
    except ValueError:
        raise PermanentMessageError("requested não é JSON") from None
    try:
        envelope = validate_tolerant(generated.MessageEnvelope, document)
    except ValidationError:
        raise PermanentMessageError("envelope de requested fora do contrato") from None
    if not supports_major(envelope.schema_version):
        raise PermanentMessageError("schemaVersion MAJOR não suportado")
    if (
        envelope.message_type != "requested"
        or envelope.emitter != "receiver"
        or envelope.module != "sum"
        or envelope.resource_type != "service"
    ):
        raise PermanentMessageError("requested de outro tipo, módulo ou emissor")
    if envelope.requested_by is None or envelope.correlation_id is None:
        raise PermanentMessageError("requested sem requestedBy ou correlationId")
    operation = envelope.operation.value
    try:
        if operation == "create":
            body = validate_tolerant(generated.ServiceRequestedCreateData, envelope.data)
            spec = body.specification
            return CreateRequest(
                operation_id=body.operation_id,
                request_digest=body.request_digest,
                requested_by=envelope.requested_by,
                correlation_id=envelope.correlation_id,
                requested_message_id=envelope.message_id,
                resource_id=envelope.resource_id,
                owner_account_id=spec.owner_account_id,
                service=spec.service,
            )
        if operation == "delete":
            body_delete = validate_tolerant(generated.ServiceRequestedDeleteData, envelope.data)
            return DeleteRequest(
                operation_id=body_delete.operation_id,
                request_digest=body_delete.request_digest,
                requested_by=envelope.requested_by,
                correlation_id=envelope.correlation_id,
                requested_message_id=envelope.message_id,
                resource_id=envelope.resource_id,
                expected_version=body_delete.resource_version,
            )
    except ValidationError:
        raise PermanentMessageError("dados de requested fora do contrato") from None
    raise PermanentMessageError("operação de requested não suportada")


async def process_request(
    pool: psycopg_pool.AsyncConnectionPool[Any],
    handler: RequestedHandler,
    data: bytes,
) -> Disposition:
    """Aplica uma mensagem e decide o destino no transporte (ACK, TERM ou RETRY)."""
    for attempt, delay in enumerate((*TRANSIENT_RETRY_DELAYS_SECONDS, None)):
        try:
            request = parse_request(data)
            async with pool.connection() as connection, connection.transaction():
                if isinstance(request, CreateRequest):
                    await handler.create(
                        connection,
                        operation_id=request.operation_id,
                        request_digest=request.request_digest,
                        requested_by=request.requested_by,
                        correlation_id=request.correlation_id,
                        requested_message_id=request.requested_message_id,
                        resource_id=request.resource_id,
                        owner_account_id=request.owner_account_id,
                        service=request.service,
                    )
                else:
                    await handler.delete(
                        connection,
                        operation_id=request.operation_id,
                        request_digest=request.request_digest,
                        requested_by=request.requested_by,
                        correlation_id=request.correlation_id,
                        requested_message_id=request.requested_message_id,
                        resource_id=request.resource_id,
                        expected_version=request.expected_version,
                    )
            return Disposition.ACK
        except PermanentMessageError as error:
            logger.error(
                "message rejected as permanently invalid", extra={"smarkee.reason": str(error)}
            )
            return Disposition.TERM
        except TRANSIENT_DATABASE_ERRORS as error:
            logger.warning(
                "transient database error while handling a request",
                extra={"smarkee.delivery.attempt": attempt + 1},
                exc_info=error,
            )
            if delay is None:
                return Disposition.RETRY
            await asyncio.sleep(delay)
    return Disposition.RETRY  # inalcançável; mantém o tipo de retorno explícito


class RequestedConsumer:
    """Consumer durável de `requested` de `sum.service` (um por Stream que o Manager lê)."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        handler: RequestedHandler,
        *,
        durable_name: str,
        stream: str = REQUESTED_STREAM,
        batch_size: int = 10,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._jetstream = jetstream
        self._pool = pool
        self._handler = handler
        self._durable_name = durable_name
        self._stream = stream
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds
        self._on_cycle = on_cycle

    async def run(self, stop: asyncio.Event) -> None:
        subscription = await self._jetstream.pull_subscribe_bind(
            consumer=self._durable_name, stream=self._stream
        )
        while not stop.is_set():
            self._on_cycle()
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

    async def settle_once(self, message: Msg) -> Literal["ack", "term", "retry"]:
        """Processa e confirma uma mensagem. Usado pelos testes e pelo laço de `run`."""
        # O contexto de trace vem no header NATS (decisão 0055); vale só para esta mensagem.
        bind_traceparent((message.headers or {}).get(TRACEPARENT_HEADER))
        bind_message_context(message.data)
        try:
            disposition = await process_request(self._pool, self._handler, message.data)
            logger.info(
                "message handled",
                extra={
                    "messaging.consumer.group.name": self._durable_name,
                    "smarkee.outcome": disposition.value,
                },
            )
        finally:
            bind_traceparent(None)
        match disposition:
            case Disposition.ACK:
                await message.ack()
            case Disposition.TERM:
                await message.term()
            case Disposition.RETRY:
                await message.nak(delay=REDELIVERY_DELAY_SECONDS)
        return disposition.value  # type: ignore[return-value]

    async def _settle(self, message: Msg) -> None:
        await self.settle_once(message)
