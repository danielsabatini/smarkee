"""Tratamento de `requested` de `sum.service` pelo Manager (decisão 0033).

Cada pedido é uma unidade atômica: quem chama abre a transação, e este handler grava a Operation e,
quando aceita, a ligação e a mensagem `desired` no outbox. Uma recusa grava só a Operation, com o
motivo. Reentrega do mesmo `operationId` não grava de novo.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from psycopg import AsyncConnection, errors

from sum_service.common.resource import SCHEMA_VERSION
from sum_service.manager.domain.decision import (
    Decision,
    Link,
    Rejected,
    decide_create,
    decide_delete,
)
from sum_service.manager.store import ssot

DESIRED_SUBJECT_PREFIX = "manager.desired.sum.service"


@dataclass(frozen=True, slots=True)
class Recorded:
    """O pedido foi gravado. `status` é `accepted` (vai ao Executor) ou `rejected` (com motivo)."""

    operation_id: str
    status: Literal["accepted", "rejected"]
    resource_id: str
    reason: str | None = None
    existing_resource_id: str | None = None
    """Só em `already_exists`: a ligação ativa que já existe, para o cliente saber qual é."""


@dataclass(frozen=True, slots=True)
class Duplicate:
    """Reentrega: a Operation já existe. Nada é gravado; o chamador confirma a mensagem."""

    operation_id: str


Outcome = Recorded | Duplicate


class RequestedHandler:
    def __init__(
        self,
        *,
        catalog: Mapping[str, tuple[str, ...]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._catalog = catalog
        self._clock = clock

    async def create(
        self,
        conn: AsyncConnection[Any],
        *,
        operation_id: str,
        request_digest: str,
        requested_by: str,
        correlation_id: str,
        requested_message_id: str,
        resource_id: str,
        owner_account_id: str,
        service: str,
    ) -> Outcome:
        """`resource_id` é atribuído pelo Receiver (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1.1)."""
        if await ssot.find_operation(conn, operation_id) is not None:
            return Duplicate(operation_id)
        # Religar um par já desligado reaproveita o recurso: o Receiver manda o `resourceId` dele.
        existing = await ssot.link_for_resource(conn, resource_id)
        active = await ssot.active_link_for(conn, owner_account_id, service)
        decision = decide_create(
            owner_account_id=owner_account_id,
            service=service,
            catalog=self._catalog,
            active_link=active,
            existing_link=existing,
        )
        if isinstance(decision, Rejected):
            return await self._reject(
                conn,
                operation_id=operation_id,
                resource_id=resource_id,
                operation_type="create",
                request_digest=request_digest,
                requested_by=requested_by,
                correlation_id=correlation_id,
                decision=decision,
            )
        if existing is not None:
            return await self._reenable(
                conn,
                existing=existing,
                desired=decision.desired,
                operation_id=operation_id,
                request_digest=request_digest,
                requested_by=requested_by,
                correlation_id=correlation_id,
                causation_id=requested_message_id,
            )
        try:
            # Savepoint: a violação do índice da ligação ativa desfaz só esta gravação.
            async with conn.transaction():
                await ssot.insert_link(
                    conn,
                    resource_id=resource_id,
                    schema_version=SCHEMA_VERSION,
                    owner_account_id=owner_account_id,
                    service=service,
                    desired=decision.desired,
                )
        except errors.UniqueViolation:
            # Outro pedido ligou o mesmo par entre a leitura e a gravação.
            raced = await ssot.active_link_for(conn, owner_account_id, service)
            return await self._reject(
                conn,
                operation_id=operation_id,
                resource_id=resource_id,
                operation_type="create",
                request_digest=request_digest,
                requested_by=requested_by,
                correlation_id=correlation_id,
                decision=Rejected(
                    "already_exists",
                    existing_resource_id=raced.resource_id if raced else None,
                ),
            )
        return await self._accept(
            conn,
            operation_id=operation_id,
            resource_id=resource_id,
            operation_type="create",
            generation=1,
            desired=decision.desired,
            request_digest=request_digest,
            requested_by=requested_by,
            correlation_id=correlation_id,
            causation_id=requested_message_id,
        )

    async def _reenable(
        self,
        conn: AsyncConnection[Any],
        *,
        existing: Link,
        desired: dict[str, Any],
        operation_id: str,
        request_digest: str,
        requested_by: str,
        correlation_id: str,
        causation_id: str,
    ) -> Outcome:
        """Liga de novo o recurso do par: novo `desired` e geração seguinte, sem recurso novo."""
        generation = existing.desired_generation + 1
        await ssot.update_link(
            conn, resource_id=existing.resource_id, desired=desired, generation=generation
        )
        return await self._accept(
            conn,
            operation_id=operation_id,
            resource_id=existing.resource_id,
            operation_type="create",
            generation=generation,
            desired=desired,
            request_digest=request_digest,
            requested_by=requested_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    async def delete(
        self,
        conn: AsyncConnection[Any],
        *,
        operation_id: str,
        request_digest: str,
        requested_by: str,
        correlation_id: str,
        requested_message_id: str,
        resource_id: str,
        expected_version: str,
    ) -> Outcome:
        if await ssot.find_operation(conn, operation_id) is not None:
            return Duplicate(operation_id)
        link = await ssot.link_for_resource(conn, resource_id)
        decision = decide_delete(link=link, expected_version=expected_version)
        if isinstance(decision, Rejected):
            return await self._reject(
                conn,
                operation_id=operation_id,
                resource_id=resource_id,
                operation_type="delete",
                request_digest=request_digest,
                requested_by=requested_by,
                correlation_id=correlation_id,
                decision=decision,
            )
        assert link is not None  # noqa: S101 (decide_delete só aceita ligação existente)
        generation = link.desired_generation + 1
        await ssot.update_link(
            conn, resource_id=resource_id, desired=decision.desired, generation=generation
        )
        return await self._accept(
            conn,
            operation_id=operation_id,
            resource_id=resource_id,
            operation_type="delete",
            generation=generation,
            desired=decision.desired,
            request_digest=request_digest,
            requested_by=requested_by,
            correlation_id=correlation_id,
            causation_id=requested_message_id,
        )

    async def _accept(
        self,
        conn: AsyncConnection[Any],
        *,
        operation_id: str,
        resource_id: str,
        operation_type: Literal["create", "delete"],
        generation: int,
        desired: dict[str, Any],
        request_digest: str,
        requested_by: str,
        correlation_id: str,
        causation_id: str,
    ) -> Recorded:
        await ssot.insert_operation(
            conn,
            operation_id=operation_id,
            resource_id=resource_id,
            operation_type=operation_type,
            desired_generation=generation,
            requested_by=requested_by,
            correlation_id=correlation_id,
            request_digest=request_digest,
            status="accepted",
            reason=None,
        )
        message_id = str(uuid.uuid7())
        await ssot.insert_outbox(
            conn,
            message_id=message_id,
            resource_id=resource_id,
            subject=f"{DESIRED_SUBJECT_PREFIX}.{resource_id}.changed",
            payload=desired_envelope(
                message_id=message_id,
                resource_id=resource_id,
                generation=generation,
                desired=desired,
                requested_by=requested_by,
                correlation_id=correlation_id,
                causation_id=causation_id,
                occurred_at=self._clock(),
            ),
        )
        return Recorded(operation_id, "accepted", resource_id)

    async def _reject(
        self,
        conn: AsyncConnection[Any],
        *,
        operation_id: str,
        resource_id: str,
        operation_type: Literal["create", "delete"],
        request_digest: str,
        requested_by: str,
        correlation_id: str,
        decision: Decision,
    ) -> Recorded:
        assert isinstance(decision, Rejected)  # noqa: S101 (só recusas chegam aqui)
        await ssot.insert_operation(
            conn,
            operation_id=operation_id,
            resource_id=resource_id,
            operation_type=operation_type,
            desired_generation=None,
            requested_by=requested_by,
            correlation_id=correlation_id,
            request_digest=request_digest,
            status="rejected",
            reason=decision.reason,
        )
        return Recorded(
            operation_id,
            "rejected",
            resource_id,
            decision.reason,
            existing_resource_id=decision.existing_resource_id,
        )


def desired_envelope(
    *,
    message_id: str,
    resource_id: str,
    generation: int,
    desired: dict[str, Any],
    requested_by: str,
    correlation_id: str,
    causation_id: str,
    occurred_at: datetime,
) -> dict[str, Any]:
    """Envelope do `desired`, sem `publishedAt` e `publishedBy` (o Publisher os preenche)."""
    return {
        "messageId": message_id,
        "schemaVersion": SCHEMA_VERSION,
        "messageType": "desired",
        "emitter": "manager",
        "module": "sum",
        "resourceType": "service",
        "resourceId": resource_id,
        "operation": "changed",
        "desiredGeneration": generation,
        "requestedBy": requested_by,
        "correlationId": correlation_id,
        "causationId": causation_id,
        "occurredAt": occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": desired,
    }
