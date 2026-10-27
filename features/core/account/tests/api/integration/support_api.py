"""Auxiliares dos testes de integração (PostgreSQL de desenvolvimento, papéis reais).

Os dados de teste entram no SSOT por SQL, com o papel da API do tipo (decisão 0098).
"""

import os
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

DATABASE_HOST = os.environ.get("CORE_TEST_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CORE_TEST_DATABASE_PORT", "5432")


def dsn(login_role: str) -> str:
    return (
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
        f" user={login_role} password={login_role} connect_timeout=3"
    )


async def connect(login_role: str) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(dsn(login_role), autocommit=True)


async def seed_account(
    api: psycopg.AsyncConnection[Any], *, email: str, requested_by: str = "anonymous"
) -> str:
    """Grava uma Account, como a admissão faria."""
    resource_id = str(uuid.uuid7())
    desired = {
        "lifecycle": "present",
        "platformAccess": "granted",
        "platformPermissions": ["core.account.get"],
        "givenName": "Ana",
        "familyName": "Souza",
        "email": email,
        "deletionProtection": True,
    }
    await api.execute(
        "INSERT INTO core.account (resource_id, schema_version, lifecycle, reconciliation,"
        " desired, desired_generation, resource_version, phase, requested_by, correlation_id)"
        " VALUES (%s, '1.0', 'present', 'active', %s, 1, 1, 'Pending', %s, %s)",
        (resource_id, Jsonb(desired), requested_by, str(uuid.uuid7())),
    )
    return resource_id


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]
