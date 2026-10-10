"""Auxiliares dos testes de integração (PostgreSQL de desenvolvimento, papéis reais)."""

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

DATABASE_HOST = os.environ.get("CORE_TEST_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CORE_TEST_DATABASE_PORT", "5432")
DEFAULT_DIGEST = "0" * 64


def dsn(login_role: str) -> str:
    return (
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=smarkee"
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


def requested_message(
    *,
    resource_type: str,
    resource_id: str,
    operation: str,
    requested_by: str,
    data: dict[str, Any],
    message_id: str | None = None,
) -> dict[str, Any]:
    """Um `requested` válido, como a API o publicaria."""
    return {
        "messageId": message_id or str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "api",
        "module": "core",
        "resourceType": resource_type,
        "resourceId": resource_id,
        "operation": operation,
        "requestedBy": requested_by,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": "2026-10-10T12:00:00Z",
        "publishedAt": "2026-10-10T12:00:00Z",
        "data": data,
    }
