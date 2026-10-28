"""Auxiliares dos testes de integração (PostgreSQL de desenvolvimento, papéis reais).

Os dados de teste entram no SSOT por SQL, com o papel da API do tipo (decisão 0098).
"""

import os
import uuid
from typing import Any

import psycopg
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


async def seed_link(
    api: psycopg.AsyncConnection[Any],
    *,
    owner: str,
    service: str = "ipm",
    lifecycle: str = "present",
    requested_by: str = "test-seed",
) -> str:
    """Grava uma ligação, como a admissão faria."""
    resource_id = str(uuid.uuid7())
    permissions = ["ipm.organization.get"] if lifecycle == "present" else []
    desired = {
        "lifecycle": lifecycle,
        "reconciliation": "active",
        "ownerAccountId": owner,
        "service": service,
        "servicePermissions": permissions,
        "managedPermissions": ["ipm.organization.get"],
    }
    await api.execute(
        "INSERT INTO sum.service (resource_id, schema_version, owner_account_id, service,"
        " lifecycle, reconciliation, desired, desired_generation, resource_version, phase,"
        " requested_by, correlation_id)"
        " VALUES (%s, '1.0', %s, %s, %s, 'active', %s, 1, 1, 'Pending', %s, %s)",
        (resource_id, owner, service, lifecycle, Jsonb(desired), requested_by, str(uuid.uuid7())),
    )
    return resource_id


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]
