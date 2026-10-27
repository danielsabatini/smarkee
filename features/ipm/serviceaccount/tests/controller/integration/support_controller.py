"""Auxiliares dos testes de integração do Controller (PostgreSQL de dev, papéis reais)."""

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ipm_serviceaccount.manager.store.ssot import SsotStore
from ipm_serviceaccount.manager.store.tables import tables_of

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


SAMPLE_KEYS: list[dict[str, str]] = [
    {
        "publicKey": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu1SU1LfVLPHCozMxH2Mo\n4lgOEePzNm0tRgeLezV6ffAt0gunVTLw7onLRnrq0/IzW7yWR7QkrmBL7jTKEn5u\n+qKhbwKfBstIs+bMY2Zkp18gnTxKLxoS2tFczGkPLPgizskuemMghRniWaoLcyeh\nkd3qqGElvW/VDL5AaWTg0nLVkjRo9z+40RQzuVaE8AkAFmxZzow3x+VJYKdjykkJ\n0iT9wCS0DRTXu269V264Vf/3jvredZiKRkgwlL9xNAwxXFMdc6U6mS0Dmj4ZW+EY\ntDV0FNsMzP5nkQa3iX7D4hFxNl9lXoB0iJhpgJmfrVfJLFSEfMyw72yW6Uq3Ohjf\nbwIDAQAB\n-----END PUBLIC KEY-----\n",  # noqa: E501
        "expiresAt": "2027-01-24T14:00:00Z",
        "fingerprint": "9" * 64,
    }
]


def requested_message(resource_id: str) -> dict[str, Any]:
    """Um `requested` de criação válido, como o Receiver o publicaria."""
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "ipm",
        "resourceType": "serviceaccount",
        "resourceId": resource_id,
        "operation": "create",
        "requestedBy": "owner-1",
        "correlationId": str(uuid.uuid7()),
        "occurredAt": "2026-10-10T12:00:00Z",
        "publishedAt": "2026-10-10T12:00:00Z",
        "data": {
            "operationId": f"op-{unique_suffix()}",
            "requestDigest": "0" * 64,
            "specification": {
                "organizationId": "org-ctl",
                "name": f"sa-{unique_suffix()}",
                "keys": SAMPLE_KEYS,
                "roles": ["ipm.serviceaccountViewer"],
                "deletionProtection": False,
            },
        },
    }


def ssot(connection: psycopg.AsyncConnection[Any]) -> SsotStore:
    """Adaptador do SSOT da service account para o Manager criar o recurso do teste."""
    return SsotStore(connection, tables_of("serviceaccount"))
