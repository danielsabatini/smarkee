"""Leitura do SSOT pelo Receiver de Grupo, somente pelas views versionadas (decisões 0004 e 0088).

O Receiver não escreve no SSOT e não lê as tabelas: lê a view `group_v1` do recurso e a
`group_operation_v1` da Operation, com o papel `ipm_group_receiver`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ipm_group.receiver.domain.records import OperationRecord, ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, lifecycle, reconciliation, phase,"
    " conditions, desired, presence, observed, observed_at, created_at, updated_at"
)
OPERATION_COLUMNS = (
    "operation_id, resource_id, operation_type, desired_generation, request_digest,"
    " operation_status, operation_status_reason, requested_by, created_at, updated_at, completed_at"
)


class SsotRepository:
    """Leitura das views do tipo, com o papel `ipm_group_receiver`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_group(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM ipm.group_v1 WHERE resource_id = %s",  # noqa: S608
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def list_groups(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM ipm.group_v1"  # noqa: S608
                " WHERE desired ->> 'organizationId' = %(organization)s"
                " AND (%(after)s::text IS NULL OR resource_id > %(after)s)"
                " ORDER BY resource_id LIMIT %(limit)s",
                {"organization": organization_id, "after": after, "limit": limit},
            )
            return [ResourceRecord(**row) for row in await cursor.fetchall()]

    async def count_groups_in(self, organization_id: str) -> int:
        query = (
            "SELECT count(*) FROM ipm.group_v1 "
            "WHERE desired ->> 'organizationId' = %s AND lifecycle = 'present'"
        )
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, (organization_id,))
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {OPERATION_COLUMNS} FROM ipm.group_operation_v1"  # noqa: S608
                " WHERE operation_id = %s",
                (operation_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else OperationRecord(**row)
