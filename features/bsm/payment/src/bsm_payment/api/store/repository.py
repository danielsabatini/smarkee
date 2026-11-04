"""Leitura do SSOT pela API, pelas views versionadas (decisão 0004).

Lê a view `payment_v1` com o papel `bsm_payment_api`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bsm_payment.api.domain.records import ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, observed_generation, lifecycle,"
    " reconciliation, phase, conditions, desired, presence, observed, observed_at,"
    " created_at, updated_at"
)


class SsotRepository:
    """Leitura das views do tipo, com o papel `bsm_payment_api`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_payment(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM bsm.payment_v1 WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def list_payments(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM bsm.payment_v1"  # noqa: S608 (constante do módulo)
                " WHERE (%(owner)s::text IS NULL OR desired ->> 'ownerAccountId' = %(owner)s)"
                " AND (%(after)s::text IS NULL OR resource_id > %(after)s)"
                " ORDER BY resource_id LIMIT %(limit)s",
                {"owner": owner, "after": after, "limit": limit},
            )
            return [ResourceRecord(**row) for row in await cursor.fetchall()]
