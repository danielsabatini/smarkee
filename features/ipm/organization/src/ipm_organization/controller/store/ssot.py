"""Adaptador de persistência do Controller no SSOT (decisão 0096).

Não decide regra de negócio: executa as gravações que o `engine/` pede, dentro da transação que ele
abre. A linha do recurso é bloqueada (`FOR UPDATE`) antes de qualquer leitura que decida uma
gravação (`docs/data/SSOT.md`, invariante 9). O Controller é o único escritor de `observed`,
`phase`, `conditions` e `failure_count`, e quem grava o `updated` no outbox (mesma transação).
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ipm_organization.common.logging_config import current_traceparent

_ROW_COLUMNS = (
    "resource_id, resource_version, desired_generation, observed_generation, lifecycle,"
    " reconciliation, failure_count, phase, conditions, desired, observed, presence,"
    " requested_by, correlation_id"
)


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
                "SELECT {columns} FROM ipm.organization WHERE resource_id = %s FOR UPDATE"
            ).format(columns=sql.SQL(_ROW_COLUMNS)),
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
        failure_count: int,
        reconciliation: str,
        changed: bool,
    ) -> int:
        """Grava a observação e devolve o `resource_version`.

        `changed` diz se algo além do instante da leitura mudou: só então a versão sobe, para uma
        reavaliação sem novidade não invalidar o `resourceVersion` que um cliente leu. A coluna
        `observed_generation` só cresce (`GREATEST` ignora o nulo) e o banco recusa um valor maior
        que `desired_generation`.
        """
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE ipm.organization SET observed = %s, presence = %s, observed_at = %s,"
                " conditions = %s, phase = %s, failure_count = %s, reconciliation = %s,"
                " observed_generation = GREATEST(observed_generation, %s),"
                " resource_version = resource_version + %s,"
                " updated_at = now() WHERE resource_id = %s RETURNING resource_version"
            ),
            (
                Jsonb(observed),
                presence,
                observed_at,
                Jsonb(conditions),
                phase,
                failure_count,
                reconciliation,
                observed_generation,
                1 if changed else 0,
                resource_id,
            ),
        )
        updated = await cursor.fetchone()
        assert updated is not None  # noqa: S101 (a linha está bloqueada)
        return int(updated["resource_version"])

    async def delete_resource(self, resource_id: str) -> None:
        await self._connection.execute(
            sql.SQL("DELETE FROM ipm.organization WHERE resource_id = %s"), (resource_id,)
        )

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO ipm.organization_outbox"
                " (message_id, resource_id, subject, payload, traceparent)"
                " VALUES (%s, %s, %s, %s, %s)"
            ),
            (message["messageId"], resource_id, subject, Jsonb(message), current_traceparent()),
        )
