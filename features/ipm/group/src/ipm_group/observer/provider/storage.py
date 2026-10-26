"""Provedor somente leitura do Grupo no banco `platform` para o Observer (decisões 0086 e 0088).

Lê `ipm.group` e `ipm.group_role`. Não escreve: o papel de login do Observer só tem `SELECT`.
Qualquer falha de banco vira `ProviderError`, que o domínio traduz em `presence = unknown`, nunca
em `absent`.
"""

import re
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

from ipm_group.observer.domain.identity import ProviderError

_RESOURCE_ID = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")

_SELECT_GROUP = """
SELECT g.organization_id,
       g.name,
       g.description,
       g.deletion_protection,
       COALESCE(
         array_agg(gr.role_name ORDER BY gr.role_name)
           FILTER (WHERE gr.role_name IS NOT NULL),
         ARRAY[]::text[]
       )
  FROM ipm.group g
  LEFT JOIN ipm.group_role gr ON gr.group_id = g.resource_id
 WHERE g.resource_id = %s
 GROUP BY g.resource_id
"""


class StateStoreConnection:
    """Acesso somente leitura ao estado do Grupo no banco `platform`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ProviderError("invalid resource_id")
        try:
            async with self._pool.connection() as connection:
                cursor = await connection.execute(_SELECT_GROUP, (resource_id,))
                row = await cursor.fetchone()
        except psycopg.Error as error:
            raise ProviderError(f"failed to read the group ({type(error).__name__})") from error
        if row is None:
            return None
        org_id, name, description, protection, roles = row
        return {
            "organizationId": org_id,
            "name": name,
            "description": description,
            "deletionProtection": protection,
            "roles": list(roles),
        }
