"""Auxiliares dos testes de integração da API (PostgreSQL de desenvolvimento, papéis reais).

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


async def seed_payment(
    api: psycopg.AsyncConnection[Any],
    *,
    owner: str,
    customer_account_id: str | None = None,
    display_name: str | None = None,
) -> str:
    """Grava um Payment Method no SSOT, como a admissão faria (`Pending`)."""
    resource_id = str(uuid.uuid7())
    customer_id = customer_account_id or owner
    desired = {
        "lifecycle": "present",
        "reconciliation": "active",
        "ownerAccountId": owner,
        "customerAccountId": customer_id,
        "displayName": display_name or f"Cartao {resource_id[:8]}",
        "provider": "mercadopago",
        "methodType": "credit_card",
        "providerToken": "sim_visa_4242",
        "deletionProtection": True,
    }
    await api.execute(
        "INSERT INTO bsm.payment (resource_id, schema_version, lifecycle, reconciliation,"
        " desired, desired_generation, observed_generation, resource_version, phase,"
        " requested_by, correlation_id)"
        " VALUES (%s, '1.0', 'present', 'active', %s, 1, NULL, 1, 'Pending', 'test-seed', %s)",
        (resource_id, Jsonb(desired), str(uuid.uuid7())),
    )
    return resource_id


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]
