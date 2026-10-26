"""Gravações de `observed` e dos resultados no SSOT de `sum.service`, para os handlers do template.

Implementa a porta `handlers/ports.py` (perfil `manager-handlers`, decisão 0080). Não decide regra:
executa o que a orquestração pede, dentro da transação que ela abre, com a linha bloqueada
(`FOR UPDATE`) antes de qualquer leitura de estado. As gravações dos pedidos (`requested`) seguem
em `store/ssot.py`.
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sum_service.common.logging_config import current_traceparent
from sum_service.manager.domain.errors import DuplicateWriteError

RESOURCE = sql.Identifier("sum", "service")
OPERATION = sql.Identifier("sum", "service_operation")
ACTION_RESULT = sql.Identifier("sum", "service_action_result")
OUTBOX = sql.Identifier("sum", "service_outbox")

_ROW_COLUMNS = (
    "resource_version, desired_generation, lifecycle, reconciliation, desired, phase,"
    " conditions, failure_count, observed_at, observed_generation"
)


class StateStore:
    """Gravações de `observed` e de resultados sobre uma conexão `autocommit`."""

    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._connection = connection

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._connection.transaction():
                yield
        except psycopg.errors.UniqueViolation:
            # Duas entregas simultâneas disputam a chave primária (docs/data/POSTGRESQL.md §8).
            raise DuplicateWriteError from None

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO {table} (message_id, resource_id, subject, payload, traceparent)"
                " VALUES (%s, %s, %s, %s, %s)"
            ).format(table=OUTBOX),
            (message["messageId"], resource_id, subject, Jsonb(message), current_traceparent()),
        )

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL("SELECT {columns} FROM {table} WHERE resource_id = %s FOR UPDATE").format(
                columns=sql.SQL(_ROW_COLUMNS), table=RESOURCE
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
    ) -> int:
        """Grava a observação e devolve o novo `resource_version`.

        `observed_generation` é a geração confirmada por esta observação, ou `None` se ela não
        confirma nenhuma. A coluna só cresce (`GREATEST` ignora o nulo), e o banco recusa um valor
        maior que `desired_generation`.
        """
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE {table} SET observed = %s, presence = %s, observed_at = %s,"
                " conditions = %s, phase = %s,"
                " observed_generation = GREATEST(observed_generation, %s),"
                " resource_version = resource_version + 1,"
                " updated_at = now() WHERE resource_id = %s RETURNING resource_version"
            ).format(table=RESOURCE),
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
        updated = await cursor.fetchone()
        assert updated is not None  # noqa: S101 (a linha está bloqueada)
        return int(updated["resource_version"])

    async def delete_resource(self, resource_id: str) -> None:
        await self._connection.execute(
            sql.SQL("DELETE FROM {table} WHERE resource_id = %s").format(table=RESOURCE),
            (resource_id,),
        )

    async def settle_operations(
        self, resource_id: str, generation: int, *, converged: bool
    ) -> None:
        """Operations da geração atual: `completed` ao convergir, senão `in_progress`.

        As de geração anterior ainda abertas foram substituídas antes de convergir: `failed`.
        """
        await self._connection.execute(
            sql.SQL(
                "UPDATE {table} SET operation_status = 'superseded', updated_at = now(),"
                " completed_at = now() WHERE resource_id = %s"
                " AND operation_status IN ('accepted', 'in_progress') AND desired_generation < %s"
            ).format(table=OPERATION),
            (resource_id, generation),
        )
        await self.set_current_operations(
            resource_id,
            generation,
            status="completed" if converged else "in_progress",
            finished=converged,
        )

    async def set_current_operations(
        self, resource_id: str, generation: int, *, status: str, finished: bool
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "UPDATE {table} SET operation_status = %s, updated_at = now(),"
                " completed_at = CASE WHEN %s THEN now() ELSE completed_at END"
                " WHERE resource_id = %s AND operation_status IN ('accepted', 'in_progress')"
                " AND desired_generation = %s"
            ).format(table=OPERATION),
            (status, finished, resource_id, generation),
        )

    async def record_action_result(
        self, *, action_id: str, resource_id: str, generation: int, outcome: str
    ) -> bool:
        """Registra o resultado do `actionId`; `False` se ele já tinha sido contabilizado."""
        cursor = await self._connection.execute(
            sql.SQL(
                "INSERT INTO {table} (action_id, resource_id, desired_generation, action_outcome)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (action_id) DO NOTHING RETURNING action_id"
            ).format(table=ACTION_RESULT),
            (action_id, resource_id, generation, outcome),
        )
        return await cursor.fetchone() is not None

    async def save_result(
        self,
        resource_id: str,
        *,
        failure_count: int,
        phase: str,
        reconciliation: str,
        conditions: list[dict[str, Any]],
    ) -> int:
        """Grava a contagem de falhas e devolve o novo `resource_version`."""
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE {table} SET failure_count = %s, phase = %s, reconciliation = %s,"
                " conditions = %s, resource_version = resource_version + 1, updated_at = now()"
                " WHERE resource_id = %s RETURNING resource_version"
            ).format(table=RESOURCE),
            (failure_count, phase, reconciliation, Jsonb(conditions), resource_id),
        )
        updated = await cursor.fetchone()
        assert updated is not None  # noqa: S101 (a linha está bloqueada)
        return int(updated["resource_version"])
