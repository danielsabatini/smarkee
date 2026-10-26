"""Auxiliares dos testes de integração (PostgreSQL de desenvolvimento, papéis reais).

O Receiver não importa o Manager: os dados de teste entram no SSOT por SQL, com o papel do Manager
do tipo, como o contrato de armazenamento (`docs/data/POSTGRESQL.md` §6) permite.
"""

import os
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

DATABASE_HOST = os.environ.get("CORE_TEST_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CORE_TEST_DATABASE_PORT", "5432")
DIGEST = "0" * 64


def dsn(login_role: str) -> str:
    return (
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
        f" user={login_role} password={login_role} connect_timeout=3"
    )


async def connect(login_role: str) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(dsn(login_role), autocommit=True)


async def seed_user(
    manager: psycopg.AsyncConnection[Any], *, organization: str, requested_by: str = "root-1"
) -> tuple[str, str]:
    """Grava um usuário da Organization e a sua Operation, como o Manager faria."""
    resource_id, operation_id = str(uuid.uuid7()), str(uuid.uuid7())
    desired = {
        "lifecycle": "present",
        "organizationId": organization,
        "givenName": "Bia",
        "familyName": "Lima",
        "email": f"repo-{unique_suffix()}@example.com",
        "permissions": ["ipm.user.get"],
        "deletionProtection": False,
    }
    await manager.execute(
        "INSERT INTO ipm.user (resource_id, schema_version, lifecycle, reconciliation,"
        " desired, desired_generation, resource_version, phase)"
        " VALUES (%s, '1.0', 'present', 'active', %s, 1, 1, 'Pending')",
        (resource_id, Jsonb(desired)),
    )
    await manager.execute(
        "INSERT INTO ipm.user_operation (operation_id, resource_id, operation_type,"
        " desired_generation, requested_by, correlation_id, request_digest, operation_status)"
        " VALUES (%s, %s, 'create', 1, %s, %s, %s, 'accepted')",
        (operation_id, resource_id, requested_by, str(uuid.uuid7()), DIGEST),
    )
    return resource_id, operation_id


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]
