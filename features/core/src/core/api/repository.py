"""Leitura do SSOT pela API, somente pelas views versionadas (decisão 0004).

A API não escreve no SSOT e não lê as tabelas: cada tipo tem a view `<tipo>_v1` do recurso e
a `<tipo>_operation_v1` da Operation, com o papel `core_<tipo>_api`.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    """Linha da view `<tipo>_v1`."""

    resource_id: str
    resource_version: int
    desired_generation: int
    lifecycle: str
    reconciliation: str
    phase: str
    conditions: list[dict[str, Any]]
    desired: dict[str, Any]
    presence: str | None
    observed: dict[str, Any] | None
    observed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """Linha da view `<tipo>_operation_v1`. `requested_by` serve só para autorizar a leitura."""

    operation_id: str
    resource_type: str
    resource_id: str
    operation_type: str
    desired_generation: int | None
    request_digest: str
    operation_status: str
    operation_status_reason: str | None
    requested_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class Repository(Protocol):
    async def get_resource(self, resource_type: str, resource_id: str) -> ResourceRecord | None: ...

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]: ...

    async def count_organizations_owned_by(self, owner: str) -> int: ...

    async def find_operation(
        self, operation_id: str, *, resource_type: str | None = None
    ) -> OperationRecord | None: ...


RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, lifecycle, reconciliation, phase,"
    " conditions, desired, presence, observed, observed_at, created_at, updated_at"
)
OPERATION_COLUMNS = (
    "operation_id, resource_id, operation_type, desired_generation, request_digest,"
    " operation_status, operation_status_reason, requested_by, created_at, updated_at, completed_at"
)
RESOURCE_TYPES = ("organization", "user")


def _resource(row: dict[str, Any]) -> ResourceRecord:
    return ResourceRecord(**row)


class PostgresRepository:
    """Uma pool por tipo: cada tipo usa o seu papel de leitura (`core_<tipo>_api`)."""

    def __init__(self, pools: dict[str, AsyncConnectionPool[Any]]) -> None:
        self._pools = pools

    async def get_resource(self, resource_type: str, resource_id: str) -> ResourceRecord | None:
        query = sql.SQL("SELECT {columns} FROM {view} WHERE resource_id = %s").format(
            columns=sql.SQL(RESOURCE_COLUMNS), view=sql.Identifier("core", f"{resource_type}_v1")
        )
        async with self._pools[resource_type].connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(query, (resource_id,))
            row = await cursor.fetchone()
        return None if row is None else _resource(row)

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        query = sql.SQL(
            "SELECT {columns} FROM core.organization_v1"
            " WHERE (%(owner)s::text IS NULL OR desired ->> 'ownerUserId' = %(owner)s)"
            " AND (%(after)s::text IS NULL OR resource_id > %(after)s)"
            " ORDER BY resource_id LIMIT %(limit)s"
        ).format(columns=sql.SQL(RESOURCE_COLUMNS))
        async with self._pools["organization"].connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(query, {"owner": owner, "after": after, "limit": limit})
            return [_resource(row) for row in await cursor.fetchall()]

    async def count_organizations_owned_by(self, owner: str) -> int:
        async with self._pools["organization"].connection() as connection:
            cursor = await connection.execute(
                "SELECT count(*) FROM core.organization_v1 WHERE desired ->> 'ownerUserId' = %s",
                (owner,),
            )
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def find_operation(
        self, operation_id: str, *, resource_type: str | None = None
    ) -> OperationRecord | None:
        for candidate in (resource_type,) if resource_type else RESOURCE_TYPES:
            query = sql.SQL("SELECT {columns} FROM {view} WHERE operation_id = %s").format(
                columns=sql.SQL(OPERATION_COLUMNS),
                view=sql.Identifier("core", f"{candidate}_operation_v1"),
            )
            async with self._pools[candidate].connection() as connection:
                cursor = connection.cursor(row_factory=dict_row)
                await cursor.execute(query, (operation_id,))
                row = await cursor.fetchone()
            if row is not None:
                return OperationRecord(resource_type=candidate, **row)
        return None
