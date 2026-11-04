"""Adaptador de persistência do Controller no SSOT (decisão 0096).

Não decide regra de negócio: executa as gravações que o `engine/` pede, dentro da transação que ele
abre. A linha do recurso é bloqueada (`FOR UPDATE`) antes de qualquer leitura que decida uma
gravação (`docs/data/SSOT.md`, invariante 9). O Controller é o único escritor de `observed`,
`phase`, `conditions` e `failure_count`, e quem grava o `updated` no outbox (mesma transação).
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from bsm_payment.common.logging_config import current_traceparent

_ROW_COLUMNS = (
    "resource_id, resource_version, desired_generation, observed_generation, lifecycle,"
    " reconciliation, failure_count, phase, conditions, desired, observed, presence,"
    " requested_by, correlation_id"
)


class ControllerSsotStore:
    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._conn = connection

    @classmethod
    @asynccontextmanager
    async def transaction(
        cls, pool: AsyncConnectionPool[Any]
    ) -> AsyncGenerator[ControllerSsotStore]:
        async with pool.connection() as conn, conn.transaction():
            yield cls(conn)

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._conn.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL("SELECT {} FROM bsm.payment WHERE resource_id = %s FOR UPDATE").format(
                sql.SQL(_ROW_COLUMNS)
            ),
            (resource_id,),
        )
        return await cursor.fetchone()

    async def save_observed(
        self,
        resource_id: str,
        *,
        observed: Mapping[str, Any],
        presence: str,
        observed_at: datetime,
        phase: str,
        conditions: list[dict[str, Any]],
        converged: bool,
        observation_generation: int,
    ) -> dict[str, Any]:
        cursor = self._conn.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE bsm.payment SET"
                " observed = CASE WHEN %(presence)s = 'unknown'"
                "   THEN observed ELSE %(observed)s END,"
                " presence = %(presence)s,"
                " observed_at = %(observed_at)s,"
                " phase = %(phase)s,"
                " conditions = %(conditions)s,"
                " failure_count = CASE WHEN %(converged)s THEN 0 ELSE failure_count END,"
                " observed_generation = CASE WHEN %(converged)s"
                "   THEN %(observation_generation)s ELSE observed_generation END,"
                " resource_version = resource_version + 1,"
                " updated_at = now()"
                " WHERE resource_id = %(resource_id)s"
                " RETURNING {}, observed_at"
            ).format(sql.SQL(_ROW_COLUMNS)),
            {
                "resource_id": resource_id,
                "observed": Jsonb(observed),
                "presence": presence,
                "observed_at": observed_at,
                "phase": phase,
                "conditions": Jsonb(conditions),
                "converged": converged,
                "observation_generation": observation_generation,
            },
        )
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"resource {resource_id} disappeared during transaction")
        return row

    async def save_action_result(
        self,
        resource_id: str,
        *,
        failure_count: int,
        phase: str,
        reconciliation: str,
        conditions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cursor = self._conn.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE bsm.payment SET"
                " failure_count = %(failure_count)s,"
                " phase = %(phase)s,"
                " reconciliation = %(reconciliation)s,"
                " conditions = %(conditions)s,"
                " resource_version = resource_version + 1,"
                " updated_at = now()"
                " WHERE resource_id = %(resource_id)s"
                " RETURNING {}, observed_at"
            ).format(sql.SQL(_ROW_COLUMNS)),
            {
                "resource_id": resource_id,
                "failure_count": failure_count,
                "phase": phase,
                "reconciliation": reconciliation,
                "conditions": Jsonb(conditions),
            },
        )
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"resource {resource_id} disappeared during transaction")
        return row

    async def delete_resource(self, resource_id: str) -> None:
        await self._conn.execute(
            "DELETE FROM bsm.payment WHERE resource_id = %s",
            (resource_id,),
        )

    async def add_to_outbox(
        self,
        message: Mapping[str, Any],
        *,
        resource_id: str,
        subject: str,
    ) -> None:
        await self._conn.execute(
            "INSERT INTO bsm.payment_outbox"
            " (message_id, resource_id, subject, payload, traceparent)"
            " VALUES (%s, %s, %s, %s, %s)",
            (
                message["messageId"],
                resource_id,
                subject,
                Jsonb(message),
                current_traceparent(),
            ),
        )
