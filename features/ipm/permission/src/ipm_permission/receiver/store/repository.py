"""Leitura do SSOT pelo Receiver, somente pelas views versionadas (decisões 0004 e 0083).

O Receiver não escreve no SSOT e não lê as tabelas: lê a view `permission_v1` do recurso e a
`permission_operation_v1` da Operation, com o papel `ipm_permission_receiver`.
"""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ipm_permission.receiver.domain.records import OperationRecord, ResourceRecord

RESOURCE_COLUMNS = (
    "resource_id, resource_version, desired_generation, lifecycle, reconciliation, phase,"
    " conditions, desired, presence, observed, observed_at, created_at, updated_at"
)
OPERATION_COLUMNS = (
    "operation_id, resource_id, operation_type, desired_generation, request_digest,"
    " operation_status, operation_status_reason, requested_by, created_at, updated_at, completed_at"
)


class SsotRepository:
    """Leitura das views do tipo, com o papel `ipm_permission_receiver`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def get_permission(self, resource_id: str) -> ResourceRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {RESOURCE_COLUMNS} FROM ipm.permission_v1 WHERE resource_id = %s",  # noqa: S608 (constante do módulo)
                (resource_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else ResourceRecord(**row)

    async def list_permissions(self, *, after: str | None, limit: int) -> list[ResourceRecord]:
        clauses = ["resource_id > %s"] if after else []
        parameters: list[Any] = [after] if after else []
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            f"SELECT {RESOURCE_COLUMNS} FROM ipm.permission_v1{where} ORDER BY resource_id LIMIT %s"  # noqa: S608 (constantes do módulo)
        )
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(query, (*parameters, limit))
            rows = await cursor.fetchall()
        return [ResourceRecord(**row) for row in rows]

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                f"SELECT {OPERATION_COLUMNS} FROM ipm.permission_operation_v1"  # noqa: S608 (constante do módulo)
                " WHERE operation_id = %s",
                (operation_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else OperationRecord(**row)
