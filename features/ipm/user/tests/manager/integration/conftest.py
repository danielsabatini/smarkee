"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`, `docker compose up -d` e a migração de
`ipm-user-manager`). Sem o banco acessível, os testes são pulados. Os testes usam
identificadores únicos e removem o que criam. As credenciais são as triviais de desenvolvimento
(cada papel de login tem senha igual ao nome, `infrastructure/dev/README.md`).
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from support_manager import Cleanup, connect


@pytest_asyncio.fixture
async def database_available() -> None:
    try:
        connection = await connect("ipm_user_manager_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    manager = await connect("ipm_user_manager_login")
    maintenance = await connect("ipm_maintenance_login")
    try:
        await manager.execute(
            "DELETE FROM ipm.user WHERE resource_id = ANY(%s)", (tracker.resource_ids,)
        )
        for suffix in ("outbox", "operation", "action_result"):
            await maintenance.execute(
                f"DELETE FROM ipm.user_{suffix} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabelas fixas)
                (tracker.resource_ids,),
            )
    finally:
        await manager.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def user_manager(
    database_available: None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("ipm_user_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def user_manager_2(
    database_available: None,
) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Segunda conexão do Manager, para os testes de concorrência."""
    connection = await connect("ipm_user_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def outbox_reader(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Leitura do outbox com o papel do Publisher (o papel do Manager só insere nele)."""
    connection = await connect("ipm_user_publisher_login")
    yield connection
    await connection.close()
