"""Provedor do Grupo no banco `platform` para o Executor (decisões 0086 e 0088).

Lê e escreve `ipm.group` e `ipm.group_role`. Cada gravação é uma transação: o Grupo e o seu
conjunto de roles mudam juntos ou não mudam. Falhas de conexão ou de tempo viram
`ProviderError` com nova tentativa; violações de restrição viram `Rejected`, sem nova tentativa.
Nenhuma query usa dados do usuário fora de parâmetros (`%s`).
"""

import re
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

from ipm_group.executor.domain.identity import ProviderError

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

_UPSERT_GROUP = """
INSERT INTO ipm.group (resource_id, organization_id, name, description, deletion_protection)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (resource_id) DO UPDATE
   SET description = EXCLUDED.description,
       deletion_protection = EXCLUDED.deletion_protection,
       updated_at = now()
"""

_DELETE_STALE_ROLES = """
DELETE FROM ipm.group_role WHERE group_id = %s AND role_name <> ALL(%s::text[])
"""

_INSERT_ROLES = """
INSERT INTO ipm.group_role (group_id, role_name)
SELECT %s, unnest(%s::text[])
ON CONFLICT DO NOTHING
"""

_DELETE_GROUP = "DELETE FROM ipm.group WHERE resource_id = %s"


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
    """Leitura e escrita transacional do Grupo no banco `platform`."""

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
                cursor = await connection.execute(_SELECT_GROUP, (resource_id,))
                row = await cursor.fetchone()
        except psycopg.Error as error:
            raise _provider_error(error, "read the group") from error
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

    async def write_record(self, resource_id: str, record: Mapping[str, Any]) -> None:
        self._check(resource_id)
        roles = list(record.get("roles", []))
        try:
            async with self._pool.connection() as connection, connection.transaction():
                await connection.execute(
                    _UPSERT_GROUP,
                    (
                        resource_id,
                        record["organizationId"],
                        record["name"],
                        record["description"],
                        record["deletionProtection"],
                    ),
                )
                await connection.execute(_DELETE_STALE_ROLES, (resource_id, roles))
                await connection.execute(_INSERT_ROLES, (resource_id, roles))
        except psycopg.Error as error:
            raise _provider_error(error, "write the group") from error

    async def delete_record(self, resource_id: str) -> None:
        self._check(resource_id)
        try:
            async with self._pool.connection() as connection:
                await connection.execute(_DELETE_GROUP, (resource_id,))
        except psycopg.Error as error:
            raise _provider_error(error, "delete the group") from error
