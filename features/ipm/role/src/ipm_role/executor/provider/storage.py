"""Provedor da Role no banco `platform` para o Executor (decisões 0083 e 0086).

Lê e escreve `ipm.role` e `ipm.role_permission`. Cada gravação é uma transação: a Role e o seu
conjunto de permissões mudam juntos ou não mudam. Falhas de conexão ou de tempo viram
`ProviderError` com nova tentativa; violações de restrição viram `Rejected`, sem nova tentativa.
Nenhuma query usa dados do usuário fora de parâmetros (`%s`).
"""

import re
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

from ipm_role.executor.domain.identity import ProviderError

_RESOURCE_ID = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")

_SELECT_ROLE = """
SELECT r.name,
       r.description,
       r.deletion_protection,
       COALESCE(
         array_agg(p.permission_key ORDER BY p.permission_key)
           FILTER (WHERE p.permission_key IS NOT NULL),
         ARRAY[]::text[]
       )
  FROM ipm.role r
  LEFT JOIN ipm.role_permission p ON p.role_id = r.resource_id
 WHERE r.resource_id = %s
 GROUP BY r.resource_id
"""

_UPSERT_ROLE = """
INSERT INTO ipm.role (resource_id, name, description, deletion_protection)
VALUES (%s, %s, %s, %s)
ON CONFLICT (resource_id) DO UPDATE
   SET name = EXCLUDED.name,
       description = EXCLUDED.description,
       deletion_protection = EXCLUDED.deletion_protection,
       updated_at = now()
"""

_DELETE_STALE_PERMISSIONS = """
DELETE FROM ipm.role_permission WHERE role_id = %s AND permission_key <> ALL(%s::text[])
"""

_INSERT_PERMISSIONS = """
INSERT INTO ipm.role_permission (role_id, permission_key)
SELECT %s, unnest(%s::text[])
ON CONFLICT DO NOTHING
"""

_DELETE_ROLE = "DELETE FROM ipm.role WHERE resource_id = %s"


def _provider_error(error: psycopg.Error, action: str) -> ProviderError:
    """Traduz o erro do banco: restrição violada não se repete; o resto, sim."""
    if isinstance(error, psycopg.errors.IntegrityError | psycopg.errors.DataError):
        return ProviderError("Rejected", retryable=False, detail=f"database rejected {action}")
    return ProviderError(
        "ExternalError",
        retryable=True,
        detail=f"database failed to {action} ({type(error).__name__})",
    )


class StateStoreConnection:
    """Leitura e escrita transacional da Role no banco `platform`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    @staticmethod
    def _check(resource_id: str) -> None:
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ProviderError("Rejected", retryable=False, detail="invalid resource_id")

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        self._check(resource_id)
        try:
            async with self._pool.connection() as connection:
                cursor = await connection.execute(_SELECT_ROLE, (resource_id,))
                row = await cursor.fetchone()
        except psycopg.Error as error:
            raise _provider_error(error, "read the role") from error
        if row is None:
            return None
        name, description, protection, permissions = row
        return {
            "name": name,
            "description": description,
            "deletionProtection": protection,
            "permissions": list(permissions),
        }

    async def write_record(self, resource_id: str, record: Mapping[str, Any]) -> None:
        self._check(resource_id)
        permissions = list(record["permissions"])
        try:
            async with self._pool.connection() as connection, connection.transaction():
                await connection.execute(
                    _UPSERT_ROLE,
                    (
                        resource_id,
                        record["name"],
                        record["description"],
                        record["deletionProtection"],
                    ),
                )
                await connection.execute(_DELETE_STALE_PERMISSIONS, (resource_id, permissions))
                await connection.execute(_INSERT_PERMISSIONS, (resource_id, permissions))
        except psycopg.Error as error:
            raise _provider_error(error, "write the role") from error

    async def delete_record(self, resource_id: str) -> None:
        self._check(resource_id)
        try:
            async with self._pool.connection() as connection:
                await connection.execute(_DELETE_ROLE, (resource_id,))
        except psycopg.Error as error:
            raise _provider_error(error, "delete the role") from error
