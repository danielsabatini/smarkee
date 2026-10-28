"""Escrita da admissão no SSOT (`docs/data/SSOT.md` §10.1 e `docs/data/POSTGRESQL.md` §8 a §11).

Não decide regra de negócio: executa as gravações que `http/admission.py` pede, dentro da
transação que ele abre. A linha do recurso é bloqueada (`FOR UPDATE`) antes de qualquer leitura de
estado que decida uma gravação (invariante 9). Quem publica o `desired` é o Publisher, a partir do
outbox gravado na mesma transação.
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from psycopg import AsyncConnection, OperationalError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from sum_service.api.domain.errors import unavailable
from sum_service.api.domain.records import ResourceRecord
from sum_service.api.domain.service import idempotency_lock_key, pair_lock_key
from sum_service.api.store.repository import RESOURCE_COLUMNS
from sum_service.common.logging_config import current_traceparent


class SsotAdmissionTransaction:
    """Gravações da admissão sobre a conexão da transação aberta."""

    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._connection = connection

    async def lock_idempotency(self, requested_by: str, key: str) -> None:
        """Serializa as requisições simultâneas com a mesma chave do mesmo solicitante."""
        await self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (idempotency_lock_key(requested_by, key),),
        )

    async def find_idempotency(self, requested_by: str, key: str) -> tuple[str, str] | None:
        """`(request_digest, resource_id)` da chave já aplicada, ou `None`."""
        cursor = await self._connection.execute(
            "SELECT request_digest, resource_id FROM sum.service_idempotency"
            " WHERE requested_by = %s AND idempotency_key = %s",
            (requested_by, key),
        )
        row = await cursor.fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

    async def record_idempotency(
        self, requested_by: str, key: str, *, request_digest: str, resource_id: str
    ) -> None:
        await self._connection.execute(
            "INSERT INTO sum.service_idempotency"
            " (requested_by, idempotency_key, request_digest, resource_id) VALUES (%s, %s, %s, %s)",
            (requested_by, key, request_digest, resource_id),
        )

    async def lock_pair(self, owner_account_id: str, service: str) -> dict[str, Any] | None:
        """Serializa a disputa pelo par dono + serviço e bloqueia o recurso dele.

        O recurso é o par: o ligado, ou, se nenhum estiver ligado, o desligado mais recente.
        """
        await self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (pair_lock_key(owner_account_id, service),),
        )
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            "SELECT resource_id, resource_version, desired_generation, lifecycle,"
            " reconciliation, desired, phase FROM sum.service"
            " WHERE owner_account_id = %s AND service = %s"
            " ORDER BY (lifecycle = 'present') DESC, updated_at DESC, resource_id DESC"
            " LIMIT 1 FOR UPDATE",
            (owner_account_id, service),
        )
        return await cursor.fetchone()

    async def insert_resource(
        self,
        resource_id: str,
        *,
        schema_version: str,
        desired: Mapping[str, Any],
        requested_by: str,
        correlation_id: str,
    ) -> None:
        await self._connection.execute(
            "INSERT INTO sum.service (resource_id, schema_version, owner_account_id, service,"
            " lifecycle, reconciliation, desired, desired_generation, resource_version, phase,"
            " requested_by, correlation_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, 'Pending', %s, %s)",
            (
                resource_id,
                schema_version,
                desired["ownerAccountId"],
                desired["service"],
                desired["lifecycle"],
                desired["reconciliation"],
                Jsonb(desired),
                requested_by,
                correlation_id,
            ),
        )

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            "SELECT resource_version, desired_generation, observed_generation, lifecycle,"
            " reconciliation, desired, phase FROM sum.service"
            " WHERE resource_id = %s FOR UPDATE",
            (resource_id,),
        )
        return await cursor.fetchone()

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        phase: str,
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None:
        """Grava o novo `desired`; devolve a geração, ou `None` se a versão não confere."""
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            "UPDATE sum.service SET lifecycle = %s, reconciliation = %s, desired = %s,"
            " desired_generation = desired_generation"
            "   + (CASE WHEN desired IS DISTINCT FROM %s THEN 1 ELSE 0 END),"
            " failure_count ="
            "   CASE WHEN desired IS DISTINCT FROM %s THEN 0 ELSE failure_count END,"
            " phase = %s, requested_by = %s, correlation_id = %s,"
            " resource_version = resource_version + 1, updated_at = now()"
            " WHERE resource_id = %s AND resource_version = %s"
            " RETURNING desired_generation",
            (
                desired["lifecycle"],
                desired["reconciliation"],
                Jsonb(desired),
                Jsonb(desired),
                Jsonb(desired),
                phase,
                requested_by,
                correlation_id,
                resource_id,
                expected_resource_version,
            ),
        )
        updated = await cursor.fetchone()
        return None if updated is None else int(updated["desired_generation"])

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None:
        await self._connection.execute(
            "INSERT INTO sum.service_outbox"
            " (message_id, resource_id, subject, payload, traceparent) VALUES (%s, %s, %s, %s, %s)",
            (message["messageId"], resource_id, subject, Jsonb(message), current_traceparent()),
        )

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            f"SELECT {RESOURCE_COLUMNS} FROM sum.service WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
            (resource_id,),
        )
        row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)


class SsotAdmissionStore:
    """Abre a transação da admissão numa conexão do pool (papel `sum_service_api`)."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[SsotAdmissionTransaction]:
        # Banco indisponível ou pool esgotado: 503 com `Retry-After`; o cliente repete (a
        # `Idempotency-Key` torna a repetição segura).
        try:
            async with self._pool.connection() as connection, connection.transaction():
                yield SsotAdmissionTransaction(connection)
        except OperationalError, PoolTimeout:
            raise unavailable() from None
