"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar e a migração de `ipm-organization-manager`. Sem o banco acessível,
os testes são pulados. Os dados de teste entram no outbox com o papel do Manager (que só insere)
e são removidos ao final.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from support import Cleanup, connect


@pytest_asyncio.fixture
async def database_available() -> None:
    try:
        connection = await connect("ipm_organization_relay_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    maintenance = await connect("ipm_maintenance_login")
    try:
        await maintenance.execute(
            "DELETE FROM ipm.organization_outbox WHERE resource_id = ANY(%s)",
            (tracker.resource_ids,),
        )
    finally:
        await maintenance.close()


@pytest_asyncio.fixture
async def organization_manager(
    database_available: None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("ipm_organization_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def relay(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("ipm_organization_relay_login")
    yield connection
    await connection.close()
