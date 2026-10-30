"""Leitura do SSOT pela API, somente pelas views versionadas (decisão 0004).

A API lê a view `account_v1` do recurso com o papel `core_account_api`. A escrita da admissão
está em `store/admission.py`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core_account.api.domain.records import RegistrationTicketRecord, ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, observed_generation, lifecycle,"
    " reconciliation, phase, conditions, desired, presence, observed, observed_at, created_at,"
    " updated_at"
)


class SsotRepository:
    """Leitura das views do tipo."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_account(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM core.account_v1 WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def get_registration_ticket(self, ticket: str) -> RegistrationTicketRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT ticket, resource_id, email, created_at, expires_at, last_resend_at "
                "FROM core.account_registration_ticket WHERE ticket = %s",
                (ticket,),
            )
            row = await cursor.fetchone()
        return None if row is None else RegistrationTicketRecord(**row)

