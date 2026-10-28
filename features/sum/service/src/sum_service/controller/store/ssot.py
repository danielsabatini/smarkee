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

from sum_service.common.logging_config import current_traceparent

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
            sql.SQL("SELECT {columns} FROM sum.service WHERE resource_id = %s FOR UPDATE").format(
                columns=sql.SQL(_ROW_COLUMNS)
            ),
            (resource_id,),
        )
        return await cursor.fetchone()

    async def resource_ids(self) -> list[str]:
        """Todas as ligações, em ordem determinística (rollout do catálogo)."""
        cursor = await self._connection.execute(
            "SELECT resource_id FROM sum.service ORDER BY resource_id"
        )
        return [str(row[0]) for row in await cursor.fetchall()]

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        generation: int,
        requested_by: str,
        correlation_id: str,
    ) -> None:
        """Grava um novo `desired` e avança a geração e a versão do recurso (linha bloqueada).

        Uma geração nova recomeça a contagem de falhas e a fase (decisão 0080).
        """
        await self._connection.execute(
            "UPDATE sum.service SET lifecycle = %s, reconciliation = %s, desired = %s,"
            " desired_generation = %s, resource_version = resource_version + 1,"
            " failure_count = 0, phase = 'Pending', requested_by = %s, correlation_id = %s,"
            " updated_at = now() WHERE resource_id = %s",
            (
                desired["lifecycle"],
                desired["reconciliation"],
                Jsonb(desired),
                generation,
                requested_by,
                correlation_id,
                resource_id,
            ),
        )

    async def delete_owned_by(self, owner_account_id: str) -> int:
        """Apaga as ligações do dono (conta removida, decisão 0044). Devolve quantas apagou."""
        cursor = await self._connection.execute(
            "DELETE FROM sum.service WHERE owner_account_id = %s", (owner_account_id,)
        )
        return cursor.rowcount

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
                "UPDATE sum.service SET observed = %s, presence = %s, observed_at = %s,"
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

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None:
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO sum.service_outbox"
                " (message_id, resource_id, subject, payload, traceparent)"
                " VALUES (%s, %s, %s, %s, %s)"
            ),
            (message["messageId"], resource_id, subject, Jsonb(message), current_traceparent()),
        )
