"""Único código com SQL do SSOT de `sum.service` (decisão 0015: o Manager é o único escritor).

Cada função recebe a conexão da unidade atômica: quem chama controla a transação. Os nomes das
tabelas e colunas seguem `features/sum/service/manager/migrations/0001-service.sql`.
"""

from dataclasses import dataclass
from typing import Any, LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sum_service_manager.domain.decision import Link
from sum_service_manager.logging_config import current_traceparent


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """Uma Operation já gravada, para tratar a reentrega sem gravar de novo."""

    operation_id: str
    resource_id: str
    request_digest: str
    operation_status: str


async def find_operation(conn: AsyncConnection[Any], operation_id: str) -> OperationRecord | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT operation_id, resource_id, request_digest, operation_status "
            "FROM sum.service_operation WHERE operation_id = %s",
            (operation_id,),
        )
        row = await cur.fetchone()
    return None if row is None else OperationRecord(**row)


async def active_link_for(
    conn: AsyncConnection[Any], owner_account_id: str, service: str
) -> Link | None:
    """A ligação ativa do par dono + serviço, bloqueada até o fim da transação."""
    return await _one_link(
        conn,
        "SELECT resource_id, resource_version, desired_generation, desired FROM sum.service "
        "WHERE owner_account_id = %s AND service = %s AND lifecycle = 'present' FOR UPDATE",
        (owner_account_id, service),
    )


async def link_for_resource(conn: AsyncConnection[Any], resource_id: str) -> Link | None:
    """A ligação pelo `resourceId`, bloqueada até o fim da transação."""
    return await _one_link(
        conn,
        "SELECT resource_id, resource_version, desired_generation, desired FROM sum.service "
        "WHERE resource_id = %s FOR UPDATE",
        (resource_id,),
    )


async def insert_link(
    conn: AsyncConnection[Any],
    *,
    resource_id: str,
    schema_version: str,
    owner_account_id: str,
    service: str,
    desired: dict[str, Any],
) -> None:
    """Grava a ligação nova. Uma ativa do mesmo par viola o índice único (`UniqueViolation`)."""
    await conn.execute(
        "INSERT INTO sum.service (resource_id, schema_version, owner_account_id, service, "
        "lifecycle, reconciliation, desired, desired_generation, resource_version, phase) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, 'Pending')",
        (
            resource_id,
            schema_version,
            owner_account_id,
            service,
            desired["lifecycle"],
            desired["reconciliation"],
            Jsonb(desired),
        ),
    )


async def update_link(
    conn: AsyncConnection[Any], *, resource_id: str, desired: dict[str, Any], generation: int
) -> None:
    """Grava um novo `desired` e avança a geração e a versão do recurso."""
    await conn.execute(
        "UPDATE sum.service SET lifecycle = %s, reconciliation = %s, desired = %s, "
        "desired_generation = %s, resource_version = resource_version + 1, "
        "phase = 'Pending', updated_at = now() WHERE resource_id = %s",
        (desired["lifecycle"], desired["reconciliation"], Jsonb(desired), generation, resource_id),
    )


async def insert_operation(
    conn: AsyncConnection[Any],
    *,
    operation_id: str,
    resource_id: str | None,
    operation_type: str,
    desired_generation: int | None,
    requested_by: str,
    correlation_id: str,
    request_digest: str,
    status: str,
    reason: str | None,
) -> None:
    await conn.execute(
        "INSERT INTO sum.service_operation (operation_id, resource_id, operation_type, "
        "desired_generation, requested_by, correlation_id, request_digest, operation_status, "
        "operation_status_reason, completed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "CASE WHEN %s = 'rejected' THEN now() ELSE NULL END)",
        (
            operation_id,
            resource_id,
            operation_type,
            desired_generation,
            requested_by,
            correlation_id,
            request_digest,
            status,
            reason,
            status,
        ),
    )


async def insert_outbox(
    conn: AsyncConnection[Any],
    *,
    message_id: str,
    resource_id: str,
    subject: str,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        "INSERT INTO sum.service_outbox (message_id, resource_id, subject, payload, traceparent) "
        "VALUES (%s, %s, %s, %s, %s)",
        (message_id, resource_id, subject, Jsonb(payload), current_traceparent()),
    )


async def _one_link(
    conn: AsyncConnection[Any], sql: LiteralString, params: tuple[Any, ...]
) -> Link | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()
    if row is None:
        return None
    return Link(
        resource_id=str(row["resource_id"]),
        resource_version=str(row["resource_version"]),
        desired_generation=int(row["desired_generation"]),
        desired=row["desired"],
    )
