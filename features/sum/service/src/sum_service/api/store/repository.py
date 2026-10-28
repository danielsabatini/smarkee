"""Leitura do SSOT pela API, somente pelas views versionadas (decisão 0004).

A API lê a view `service_v1` do recurso com o papel `sum_service_api`. A escrita da admissão
está em `store/admission.py`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from sum_service.api.domain.records import ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, observed_generation, lifecycle,"
    " reconciliation, phase, conditions, desired, presence, observed, observed_at, created_at,"
    " updated_at"
)


class SsotRepository:
    """Leitura das views do tipo."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_service(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM sum.service_v1 WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def services_of(self, owner_account_id: str) -> list[ResourceRecord]:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM sum.service_v1"  # noqa: S608 (constante do módulo)
                " WHERE desired ->> 'ownerAccountId' = %s ORDER BY resource_id",
                (owner_account_id,),
            )
            return [ResourceRecord(**row) for row in await cursor.fetchall()]
