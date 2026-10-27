"""Auxiliares dos testes de integração (PostgreSQL de desenvolvimento, papéis reais).

Os dados de teste entram no SSOT por SQL, com o papel da API do tipo (decisão 0098).
"""

import os
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

DATABASE_HOST = os.environ.get("BSM_TEST_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("BSM_TEST_DATABASE_PORT", "5432")


def dsn(login_role: str) -> str:
    return (
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
        f" user={login_role} password={login_role} connect_timeout=3"
    )


async def connect(login_role: str) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(dsn(login_role), autocommit=True)


async def seed_account(
    api: psycopg.AsyncConnection[Any],
    *,
    owner: str,
    display_name: str | None = None,
) -> str:
    """Grava uma Billing Account, como a admissão faria (já `Ready`)."""
    resource_id = str(uuid.uuid7())
    desired = {
        "lifecycle": "present",
        "displayName": display_name or f"test-account-{unique_suffix()}",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.com.br"],
        "ownerAccountId": owner,
        "deletionProtection": False,
    }
    await api.execute(
        "INSERT INTO bsm.account (resource_id, schema_version, lifecycle, reconciliation,"
        " desired, desired_generation, resource_version, phase, observed_generation,"
        " requested_by, correlation_id)"
        " VALUES (%s, '1.0', 'present', 'active', %s, 1, 1, 'Ready', 1, %s, %s)",
        (resource_id, Jsonb(desired), owner, str(uuid.uuid7())),
    )
    return resource_id


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]
