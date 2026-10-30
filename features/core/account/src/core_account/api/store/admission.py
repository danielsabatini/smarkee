"""Escrita da admissão no SSOT (`docs/data/SSOT.md` §10.1 e `docs/data/POSTGRESQL.md` §8 a §11).

Não decide regra de negócio: executa as gravações que `http/admission.py` pede, dentro da
transação que ele abre. A linha do recurso é bloqueada (`FOR UPDATE`) antes de qualquer leitura de
estado que decida uma gravação (invariante 9). Quem publica o `desired` é o Publisher, a partir do
outbox gravado na mesma transação.
"""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection, OperationalError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from core_account.api.domain.account import UniqueValue
from core_account.api.domain.errors import unavailable
from core_account.api.domain.records import RegistrationTicketRecord, ResourceRecord
from core_account.api.store.repository import RESOURCE_COLUMNS
from core_account.common.logging_config import current_traceparent


class SsotAdmissionTransaction:
    """Gravações da admissão sobre a conexão da transação aberta."""

    def __init__(self, connection: AsyncConnection[Any]) -> None:
        self._connection = connection

    async def lock_idempotency(self, requested_by: str, key: str) -> None:
        """Serializa as requisições simultâneas com a mesma chave do mesmo solicitante."""
        await self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"core.account.idempotency:{requested_by}:{key}",),
        )

    async def find_idempotency(self, requested_by: str, key: str) -> tuple[str, str] | None:
        """`(request_digest, resource_id)` da chave já aplicada, ou `None`."""
        cursor = await self._connection.execute(
            "SELECT request_digest, resource_id FROM core.account_idempotency"
            " WHERE requested_by = %s AND idempotency_key = %s",
            (requested_by, key),
        )
        row = await cursor.fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

    async def record_idempotency(
        self, requested_by: str, key: str, *, request_digest: str, resource_id: str
    ) -> None:
        await self._connection.execute(
            "INSERT INTO core.account_idempotency"
            " (requested_by, idempotency_key, request_digest, resource_id) VALUES (%s, %s, %s, %s)",
            (requested_by, key, request_digest, resource_id),
        )

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool:
        """Serializa a disputa pelo e-mail e informa se outra conta ativa o ocupa."""
        await self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (unique.lock_key,)
        )
        cursor = await self._connection.execute(
            "SELECT 1 FROM core.account"
            " WHERE lifecycle = 'present' AND desired ->> %s = %s AND resource_id <> %s LIMIT 1",
            (unique.field, unique.value, excluding_resource_id),
        )
        return await cursor.fetchone() is not None

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
            "INSERT INTO core.account (resource_id, schema_version, lifecycle,"
            " reconciliation, desired, desired_generation, resource_version, phase,"
            " requested_by, correlation_id)"
            " VALUES (%s, %s, %s, 'active', %s, 1, 1, 'Pending', %s, %s)",
            (
                resource_id,
                schema_version,
                desired["lifecycle"],
                Jsonb(desired),
                requested_by,
                correlation_id,
            ),
        )

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            "SELECT resource_version, desired_generation, observed_generation, lifecycle,"
            " reconciliation, desired, phase FROM core.account"
            " WHERE resource_id = %s FOR UPDATE",
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
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None:
        """Grava o novo `desired`; devolve a geração, ou `None` se a versão não confere."""
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            "UPDATE core.account SET lifecycle = %s, reconciliation = %s, desired = %s,"
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
                reconciliation,
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
            "INSERT INTO core.account_outbox"
            " (message_id, resource_id, subject, payload, traceparent) VALUES (%s, %s, %s, %s, %s)",
            (message["messageId"], resource_id, subject, Jsonb(message), current_traceparent()),
        )

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            f"SELECT {RESOURCE_COLUMNS} FROM core.account WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
            (resource_id,),
        )
        row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def find_account_by_email(self, email: str) -> ResourceRecord | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        query = (
            f"SELECT {RESOURCE_COLUMNS} FROM core.account "  # noqa: S608 (constante do módulo)
            "WHERE lifecycle = 'present' AND desired->>'email' = %s"
        )
        await cursor.execute(query, (email,))
        row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def create_registration_ticket(
        self, ticket: str, resource_id: str, email: str, expires_at: datetime
    ) -> None:
        await self._connection.execute(
            "INSERT INTO core.account_registration_ticket (ticket, resource_id, email, expires_at) "
            "VALUES (%s, %s, %s, %s)",
            (ticket, resource_id, email, expires_at),
        )

    async def get_registration_ticket(self, ticket: str) -> RegistrationTicketRecord | None:
        cursor = self._connection.cursor(row_factory=dict_row)
        await cursor.execute(
            "SELECT ticket, resource_id, email, created_at, expires_at, last_resend_at "
            "FROM core.account_registration_ticket WHERE ticket = %s FOR UPDATE",
            (ticket,),
        )
        row = await cursor.fetchone()
        return None if row is None else RegistrationTicketRecord(**row)

    async def update_ticket_resend(self, ticket: str, resend_at: datetime) -> None:
        await self._connection.execute(
            "UPDATE core.account_registration_ticket SET last_resend_at = %s WHERE ticket = %s",
            (resend_at, ticket),
        )



class SsotAdmissionStore:
    """Abre a transação da admissão numa conexão do pool (papel `core_account_api`)."""

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
