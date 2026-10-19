"""Leitura do SSOT pelo Receiver, somente pelas views versionadas (decisão 0004).

O Receiver não escreve no SSOT e não lê as tabelas: lê a view `organization_v1` do recurso e a
`organization_operation_v1` da Operation, com o papel `ipm_organization.receiver`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ipm_organization.receiver.domain.records import OperationRecord, ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, lifecycle, reconciliation, phase,"
    " conditions, desired, presence, observed, observed_at, created_at, updated_at"
)
OPERATION_COLUMNS = (
    "operation_id, resource_id, operation_type, desired_generation, request_digest,"
    " operation_status, operation_status_reason, requested_by, created_at, updated_at, completed_at"
)


class PostgresRepository:
    """Leitura das views do tipo, com o papel `ipm_organization.receiver`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_organization(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM ipm.organization_v1 WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM ipm.organization_v1"  # noqa: S608 (constante do módulo)
                " WHERE (%(owner)s::text IS NULL OR desired ->> 'ownerAccountId' = %(owner)s)"
                " AND (%(after)s::text IS NULL OR resource_id > %(after)s)"
                " ORDER BY resource_id LIMIT %(limit)s",
                {"owner": owner, "after": after, "limit": limit},
            )
            return [ResourceRecord(**row) for row in await cursor.fetchall()]

    async def count_organizations_owned_by(self, owner: str) -> int:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT count(*) FROM ipm.organization_v1 WHERE desired ->> 'ownerAccountId' = %s",
                (owner,),
            )
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {OPERATION_COLUMNS} FROM ipm.organization_operation_v1"  # noqa: S608 (constante do módulo)
                " WHERE operation_id = %s",
                (operation_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else OperationRecord(**row)
