"""Auxiliares dos testes de integração do Controller (PostgreSQL de dev, papéis reais)."""

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATABASE_HOST = os.environ.get("IPM_TEST_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("IPM_TEST_DATABASE_PORT", "5432")


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


async def seed_organization(api: psycopg.AsyncConnection[Any], resource_id: str) -> None:
    """Grava o recurso como a admissão da API o grava (decisão 0098), sem passar pelo loop."""
    desired = {
        "lifecycle": "present",
        "name": f"acme-{unique_suffix()}",
        "platformAccess": "granted",
        "deletionProtection": False,
        "ownerAccountId": "owner-1",
    }
    await api.execute(
        "INSERT INTO ipm.organization (resource_id, schema_version, lifecycle, reconciliation,"
        " desired, desired_generation, resource_version, phase, requested_by, correlation_id)"
        " VALUES (%s, '1.0', 'present', 'active', %s, 1, 1, 'Pending', 'owner-1', %s)",
        (resource_id, Jsonb(desired), str(uuid.uuid7())),
    )
