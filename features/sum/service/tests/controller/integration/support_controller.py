"""Auxiliares dos testes de integração do Controller (PostgreSQL de dev, papéis reais)."""

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATABASE_HOST = os.environ.get("SUM_TEST_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("SUM_TEST_DATABASE_PORT", "5432")


def dsn(login_role: str) -> str:
    return (
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
        f" user={login_role} password={login_role} connect_timeout=3"
    )


async def connect(login_role: str) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(dsn(login_role), autocommit=True)


@dataclass
class Cleanup:
    """Identificadores criados por um teste, removidos ao final com os papéis que podem."""

    resource_ids: list[str] = field(default_factory=lambda: [])

    def track(self, resource_id: str) -> str:
        self.resource_ids.append(resource_id)
        return resource_id


async def fetch_one(
    connection: psycopg.AsyncConnection[Any], query: str, *parameters: Any
) -> dict[str, Any] | None:
    cursor = connection.cursor(row_factory=dict_row)
    await cursor.execute(query, parameters)  # type: ignore[arg-type]
    return await cursor.fetchone()


async def fetch_all(
    connection: psycopg.AsyncConnection[Any], query: str, *parameters: Any
) -> list[dict[str, Any]]:
    cursor = connection.cursor(row_factory=dict_row)
    await cursor.execute(query, parameters)  # type: ignore[arg-type]
    return await cursor.fetchall()


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


PERMISSIONS = ["ipm.organization.create", "ipm.organization.get"]


async def seed_link(
    api: psycopg.AsyncConnection[Any],
    resource_id: str,
    *,
    owner: str,
    lifecycle: str = "present",
) -> None:
    """Grava a ligação como a admissão da API a grava (decisão 0098), sem passar pelo loop."""
    desired = {
        "lifecycle": lifecycle,
        "reconciliation": "active",
        "ownerAccountId": owner,
        "service": "ipm",
        "servicePermissions": PERMISSIONS if lifecycle == "present" else [],
        "managedPermissions": PERMISSIONS,
    }
    await api.execute(
        "INSERT INTO sum.service (resource_id, schema_version, owner_account_id, service,"
        " lifecycle, reconciliation, desired, desired_generation, resource_version, phase,"
        " requested_by, correlation_id)"
        " VALUES (%s, '1.0', %s, 'ipm', %s, 'active', %s, 1, 1, 'Pending', 'test-seed', %s)",
        (resource_id, owner, lifecycle, Jsonb(desired), str(uuid.uuid7())),
    )
