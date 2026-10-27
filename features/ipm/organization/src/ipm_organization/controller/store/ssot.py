"""Adaptador de persistência do Controller no SSOT (decisão 0096).

Executa as operações de leitura sob lock e atualização atômica de status, observação e condições.
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class ControllerSsotStore:
    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._connection = connection

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        async with self._connection.transaction():
            yield

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "SELECT resource_id, desired_generation, observed_generation, resource_version,"
                " lifecycle, reconciliation, failure_count, phase, conditions, desired, observed"
                " FROM ipm.organization WHERE resource_id = %s FOR UPDATE"
            ),
            (resource_id,),
        )
        return await cursor.fetchone()

    async def save_observation(
        self,
        resource_id: str,
        *,
        observed: Mapping[str, Any],
        presence: str,
        observed_at: Any,
        conditions: list[dict[str, Any]],
        phase: str,
        observed_generation: int | None,
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "UPDATE ipm.organization SET observed = %s, presence = %s, observed_at = %s,"
                " conditions = %s, phase = %s,"
                " observed_generation = GREATEST(observed_generation, %s),"
                " resource_version = resource_version + 1,"
                " updated_at = now() WHERE resource_id = %s"
            ),
            (
                Jsonb(observed),
                presence,
                observed_at,
                Jsonb(conditions),
                phase,
                observed_generation,
                resource_id,
            ),
        )

    async def record_failure(self, resource_id: str, *, count: int) -> None:
        await self._connection.execute(
            sql.SQL(
                "UPDATE ipm.organization SET failure_count = %s, updated_at = now()"
                " WHERE resource_id = %s"
            ),
            (count, resource_id),
        )

    async def clear_failures(self, resource_id: str) -> None:
        await self._connection.execute(
            sql.SQL(
                "UPDATE ipm.organization SET failure_count = 0, updated_at = now()"
                " WHERE resource_id = %s"
            ),
            (resource_id,),
        )

    async def delete_resource(self, resource_id: str) -> None:
        await self._connection.execute(
            sql.SQL("DELETE FROM ipm.organization WHERE resource_id = %s"),
            (resource_id,),
        )

    async def settle_operations(
        self, resource_id: str, generation: int, *, converged: bool
    ) -> None:
        status = "succeeded" if converged else "failed"
        await self._connection.execute(
            sql.SQL(
                "UPDATE ipm.organization_operation SET operation_status = %s, completed_at = now()"
                " WHERE resource_id = %s AND desired_generation <= %s"
                " AND operation_status = 'pending'"
            ),
            (status, resource_id, generation),
        )
