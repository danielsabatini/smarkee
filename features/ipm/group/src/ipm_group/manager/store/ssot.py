"""Adaptador do SSOT em PostgreSQL: toda a leitura e gravação do Manager (`docs/SSOT.md`).

Não decide regra de negócio: executa as gravações que a orquestração (`handlers/`) pede, dentro
da transação que ela abre. A linha do recurso é bloqueada (`FOR UPDATE`) antes de qualquer leitura
de estado que decida uma gravação (invariante 9).
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ipm_group.common.logging_config import current_traceparent
from ipm_group.manager.domain.errors import DuplicateWriteError
from ipm_group.manager.domain.policy import OwnerQuota, UniqueValue
from ipm_group.manager.store.tables import Tables

_ROW_COLUMNS = (
    "resource_version, desired_generation, lifecycle, reconciliation, desired, phase,"
    " conditions, failure_count, observed_at, observed_generation"
)


class SsotStore:
    """Gravações do Manager sobre uma conexão `autocommit` e as tabelas do tipo."""

    def __init__(self, connection: AsyncConnection[Any], tables: Tables) -> None:
        self._connection = connection
        self._tables = tables

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        try:
            async with self._connection.transaction():
                yield
        except psycopg.errors.UniqueViolation:
            raise DuplicateWriteError from None

    # ------------------------------------------------------------------ requested

    async def recorded_digest(self, operation_id: str) -> str | None:
        cursor = await self._connection.execute(
            sql.SQL("SELECT request_digest FROM {table} WHERE operation_id = %s").format(
                table=self._tables.operation
            ),
            (operation_id,),
        )
        row = await cursor.fetchone()
        return None if row is None else str(row[0])

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool:
        """Serializa a disputa pelo valor e informa se outro recurso já o ocupa."""
        await self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (unique.lock_key,)
        )
        cursor = await self._connection.execute(
            sql.SQL(
                "SELECT 1 FROM {table} WHERE desired ->> {field} = %s AND resource_id <> %s"
                " AND (%s::text IS NULL OR desired ->> {scope} = %s)"
                " AND lifecycle = 'present' LIMIT 1"
            ).format(
                table=self._tables.resource,
                field=sql.Literal(unique.field),
                scope=sql.Literal(unique.scope_field or unique.field),
            ),
            (
                unique.value,
                excluding_resource_id,
                unique.scope_value,
                unique.scope_value,
            ),
        )
        return await cursor.fetchone() is not None

    async def owned_count(self, quota: OwnerQuota) -> int:
        """Serializa as transações do dono e conta os recursos que ele já tem."""
        await self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (quota.lock_key,)
        )
        cursor = await self._connection.execute(
            sql.SQL(
                "SELECT count(*) FROM {table}"
                " WHERE desired ->> {field} = %s AND lifecycle = 'present'"
            ).format(table=self._tables.resource, field=sql.Literal(quota.field)),
            (quota.owner,),
        )
        row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def insert_resource(
        self, resource_id: str, *, schema_version: str, desired: Mapping[str, Any]
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO {table} (resource_id, schema_version, lifecycle, reconciliation,"
                " desired, desired_generation, resource_version, phase)"
                " VALUES (%s, %s, %s, 'active', %s, 1, 1, 'Pending')"
            ).format(table=self._tables.resource),
            (resource_id, schema_version, desired["lifecycle"], Jsonb(desired)),
        )

    async def lock_for_request(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "SELECT resource_version, desired_generation, observed_generation, lifecycle,"
                " reconciliation, desired, phase FROM {table} WHERE resource_id = %s FOR UPDATE"
            ).format(table=self._tables.resource),
            (resource_id,),
        )
        return await cursor.fetchone()

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        reconciliation: str,
        phase: str,
        expected_resource_version: int | None,
    ) -> int | None:
        """Grava o novo `desired`; devolve a geração, ou `None` se a versão não confere."""
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE {table} SET lifecycle = %s, reconciliation = %s, desired = %s,"
                " desired_generation = desired_generation"
                "   + (CASE WHEN desired IS DISTINCT FROM %s THEN 1 ELSE 0 END),"
                " failure_count ="
                "   CASE WHEN desired IS DISTINCT FROM %s THEN 0 ELSE failure_count END,"
                " phase = %s, resource_version = resource_version + 1, updated_at = now()"
                " WHERE resource_id = %s AND resource_version = %s"
                " RETURNING desired_generation"
            ).format(table=self._tables.resource),
            (
                desired["lifecycle"],
                reconciliation,
                Jsonb(desired),
                Jsonb(desired),
                Jsonb(desired),
                phase,
                resource_id,
                expected_resource_version,
            ),
        )
        updated = await cursor.fetchone()
        return None if updated is None else int(updated["desired_generation"])

    async def insert_operation(
        self,
        *,
        operation_id: str,
        resource_id: str,
        operation_type: str,
        generation: int | None,
        requested_by: str,
        correlation_id: str,
        request_digest: str,
        status: str,
        reason: str | None,
        completed_at: Any,
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO {table} (operation_id, resource_id, operation_type,"
                " desired_generation, requested_by, correlation_id, request_digest,"
                " operation_status, operation_status_reason, completed_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(table=self._tables.operation),
            (
                operation_id,
                resource_id,
                operation_type,
                generation,
                requested_by,
                correlation_id,
                request_digest,
                status,
                reason,
                completed_at,
            ),
        )

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO {table} (message_id, resource_id, subject, payload, traceparent)"
                " VALUES (%s, %s, %s, %s, %s)"
            ).format(table=self._tables.outbox),
            (message["messageId"], resource_id, subject, Jsonb(message), current_traceparent()),
        )

    # ------------------------------------------------------------------ observed e resultados

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL("SELECT {columns} FROM {table} WHERE resource_id = %s FOR UPDATE").format(
                columns=sql.SQL(_ROW_COLUMNS), table=self._tables.resource
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
        """Grava a observação e devolve o novo `resource_version`."""
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE {table} SET observed = %s, presence = %s, observed_at = %s,"
                " conditions = %s, phase = %s,"
                " observed_generation = GREATEST(observed_generation, %s),"
                " resource_version = resource_version + 1,"
                " updated_at = now() WHERE resource_id = %s RETURNING resource_version"
            ).format(table=self._tables.resource),
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
        assert updated is not None  # noqa: S101
        return int(updated["resource_version"])

    async def delete_resource(self, resource_id: str) -> None:
        await self._connection.execute(
            sql.SQL("DELETE FROM {table} WHERE resource_id = %s").format(
                table=self._tables.resource
            ),
            (resource_id,),
        )

    async def settle_operations(
        self, resource_id: str, generation: int, *, converged: bool
    ) -> None:
        """Operations da geração atual: `completed` ao convergir, senão `in_progress`."""
        await self._connection.execute(
            sql.SQL(
                "UPDATE {table} SET operation_status = 'superseded', updated_at = now(),"
                " completed_at = now() WHERE resource_id = %s"
                " AND operation_status IN ('accepted', 'in_progress') AND desired_generation < %s"
            ).format(table=self._tables.operation),
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
            ).format(table=self._tables.operation),
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
            ).format(table=self._tables.action_result),
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
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE {table} SET failure_count = %s, phase = %s, reconciliation = %s,"
                " conditions = %s, resource_version = resource_version + 1, updated_at = now()"
                " WHERE resource_id = %s RETURNING resource_version"
            ).format(table=self._tables.resource),
            (failure_count, phase, reconciliation, Jsonb(conditions), resource_id),
        )
        updated = await cursor.fetchone()
        assert updated is not None  # noqa: S101
        return int(updated["resource_version"])
