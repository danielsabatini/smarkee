"""Leituras de `sum.service` para o Receiver (decisão 0033).

Só `SELECT` nas views versionadas (`sum.service_v1`, `sum.service_operation_v1`), com o papel
`sum_service_receiver`. O Receiver nunca grava no SSOT: quem grava é o Manager, por `requested`.
"""

from typing import Any

from psycopg_pool import AsyncConnectionPool


class Repository:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def link(self, resource_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT resource_id, resource_version, desired_generation, phase, conditions, desired, "
            "observed, created_at, updated_at FROM sum.service_v1 WHERE resource_id = %s",
            (resource_id,),
        )

    async def links_of(self, owner_user_id: str) -> list[dict[str, Any]]:
        """Ligações do dono, ordenadas por `resource_id` (a ordem é determinística)."""
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT resource_id, resource_version, desired_generation, phase, conditions, "
                "desired, observed, created_at, updated_at FROM sum.service_v1 "
                "WHERE desired ->> 'ownerUserId' = %s ORDER BY resource_id",
                (owner_user_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def active_link_for(self, owner_user_id: str, service: str) -> str | None:
        row = await self._one(
            "SELECT resource_id FROM sum.service_v1 WHERE desired ->> 'ownerUserId' = %s "
            "AND desired ->> 'service' = %s AND lifecycle = 'present'",
            (owner_user_id, service),
        )
        return None if row is None else str(row["resource_id"])

    async def operation(self, operation_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT operation_id, resource_id, operation_type, request_digest, operation_status, "
            "operation_status_reason, requested_by, created_at, updated_at, completed_at "
            "FROM sum.service_operation_v1 WHERE operation_id = %s",
            (operation_id,),
        )

    async def operation_of(self, resource_id: str, operation_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT operation_id, resource_id, operation_type, request_digest, operation_status, "
            "operation_status_reason, requested_by, created_at, updated_at, completed_at "
            "FROM sum.service_operation_v1 WHERE operation_id = %s AND resource_id = %s",
            (operation_id, resource_id),
        )

    async def _one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(sql, params)
            row = await cursor.fetchone()
        return None if row is None else dict(row)
