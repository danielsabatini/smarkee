"""Leitura do SSOT pela API de Grupo, somente pelas views versionadas (decisões 0004, 0088 e 0098).

A API lê a view `group_v1` com o papel `ipm_group_api`. A escrita da admissão está em
`store/admission.py`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ipm_group.api.domain.records import ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, observed_generation, lifecycle,"
    " reconciliation, phase, conditions, desired, presence, observed, observed_at, created_at,"
    " updated_at"
)


class SsotRepository:
    """Leitura das views do tipo, com o papel `ipm_group_api`."""

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
