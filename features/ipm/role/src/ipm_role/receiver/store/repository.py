"""Leitura do SSOT pelo Receiver, somente pelas views versionadas (decisões 0004 e 0083).

O Receiver não escreve no SSOT e não lê as tabelas: lê a view `role_v1` do recurso e a
`role_operation_v1` da Operation, com o papel `ipm_role_receiver`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ipm_role.receiver.domain.records import OperationRecord, ResourceRecord

PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles predefinidas (decisão 0092)."""

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, lifecycle, reconciliation, phase,"
    " conditions, desired, presence, observed, observed_at, created_at, updated_at"
)
OPERATION_COLUMNS = (
    "operation_id, resource_id, operation_type, desired_generation, request_digest,"
    " operation_status, operation_status_reason, requested_by, created_at, updated_at, completed_at"
)


class SsotRepository:
    """Leitura das views do tipo, com o papel `ipm_role_receiver`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_role(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM ipm.role_v1 WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def list_roles(
        self, *, organization_id: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        # As predefinidas pertencem a `core` (dado anterior à decisão 0092 não tem o campo).
        owners = [PLATFORM_ORGANIZATION_ID]
        if organization_id is not None and organization_id != PLATFORM_ORGANIZATION_ID:
            owners.append(organization_id)
        query = (
            f"SELECT {RESOURCE_COLUMNS} FROM ipm.role_v1"  # noqa: S608 (constantes do módulo)
            " WHERE COALESCE(desired ->> 'organizationId', %(core)s) = ANY(%(owners)s::text[])"
            " AND (%(after)s::text IS NULL OR resource_id > %(after)s)"
            " ORDER BY resource_id LIMIT %(limit)s"
        )
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                query,
                {
                    "core": PLATFORM_ORGANIZATION_ID,
                    "owners": owners,
                    "after": after,
                    "limit": limit,
                },
            )
            rows = await cursor.fetchall()
        return [ResourceRecord(**row) for row in rows]

    async def count_custom_roles_in(self, organization_id: str) -> int:
        query = (
            "SELECT count(*) FROM ipm.role_v1"
            " WHERE desired ->> 'organizationId' = %s AND lifecycle = 'present'"
        )
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, (organization_id,))
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {OPERATION_COLUMNS} FROM ipm.role_operation_v1 WHERE operation_id = %s",  # noqa: S608 (constante do módulo)
                (operation_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else OperationRecord(**row)
