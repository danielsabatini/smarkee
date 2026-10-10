"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`, `docker compose up -d` e a migração do
`core`). Sem o banco acessível, os testes são pulados. Os testes usam identificadores únicos e
removem o que criam. As credenciais são as triviais de desenvolvimento, documentadas em
`infrastructure/dev/README.md` (cada papel de login tem senha igual ao nome).
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from support import Cleanup, connect


@pytest_asyncio.fixture
async def database_available() -> None:
    try:
        connection = await connect("core_relay_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    managers = {
        "organization": await connect("core_organization_manager_login"),
        "user": await connect("core_user_manager_login"),
    }
    maintenance = await connect("core_maintenance_login")
    try:
        for resource_type, connection in managers.items():
            await connection.execute(
                sql.SQL("DELETE FROM {table} WHERE resource_id = ANY(%s)").format(
                    table=sql.Identifier("core", resource_type)
                ),
                (tracker.resource_ids,),
            )
        for resource_type in managers:
            for suffix in ("outbox", "operation", "action_result"):
                await maintenance.execute(
                    sql.SQL("DELETE FROM {table} WHERE resource_id = ANY(%s)").format(
                        table=sql.Identifier("core", f"{resource_type}_{suffix}")
                    ),
                    (tracker.resource_ids,),
                )
    finally:
        for connection in (*managers.values(), maintenance):
            await connection.close()


@pytest_asyncio.fixture
async def organization_manager(
    database_available: None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("core_organization_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def organization_manager_2(
    database_available: None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Segunda conexão do Manager, para os testes de concorrência."""
    connection = await connect("core_organization_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def user_manager(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("core_user_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def relay(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Papel de leitura do outbox (o Manager só insere nele)."""
    connection = await connect("core_relay_login")
    yield connection
    await connection.close()
