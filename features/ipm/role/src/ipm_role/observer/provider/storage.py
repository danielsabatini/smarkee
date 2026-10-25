"""Provedor somente leitura da Role no banco `platform` para o Observer (decisões 0083 e 0086).

Lê `ipm.role` e `ipm.role_permission`. Não escreve: o papel de login do Observer só tem `SELECT`.
Qualquer falha de banco vira `ProviderError`, que o domínio traduz em `presence = unknown`, nunca
em `absent`.
"""

import re
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

from ipm_role.observer.domain.identity import ProviderError

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


class StateStoreConnection:
    """Acesso somente leitura ao estado da Role no banco `platform`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ProviderError("invalid resource_id")
        try:
            async with self._pool.connection() as connection:
                cursor = await connection.execute(_SELECT_ROLE, (resource_id,))
                row = await cursor.fetchone()
        except psycopg.Error as error:
            raise ProviderError(f"failed to read the role ({type(error).__name__})") from error
        if row is None:
            return None
        name, description, protection, permissions = row
        return {
            "name": name,
            "description": description,
            "deletionProtection": protection,
            "permissions": list(permissions),
        }
