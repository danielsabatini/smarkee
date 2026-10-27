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


async def seed_user(
    api: psycopg.AsyncConnection[Any], *, organization: str, requested_by: str = "test-root"
) -> str:
    """Grava um usuário da Organization, como a admissão faria."""
    resource_id = str(uuid.uuid7())
    desired = {
        "lifecycle": "present",
        "organizationId": organization,
        "givenName": "Bia",
        "familyName": "Lima",
        "email": f"repo-{unique_suffix()}@example.com",
        "roles": ["ipm.userViewer"],
        "groups": [],
        "deletionProtection": False,
    }
    await api.execute(
        "INSERT INTO ipm.user (resource_id, schema_version, lifecycle, reconciliation,"
        " desired, desired_generation, resource_version, phase, requested_by, correlation_id)"
        " VALUES (%s, '1.0', 'present', 'active', %s, 1, 1, 'Pending', %s, %s)",
        (resource_id, Jsonb(desired), requested_by, str(uuid.uuid7())),
    )
    return resource_id


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]
