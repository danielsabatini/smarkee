"""Fixtures de integração do Controller: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar com a migração `0002-serviceaccount-controller`. Sem o banco acessível,
os testes são pulados. O recurso é criado pelo Manager (como o loop faria) e o Controller roda com
o próprio papel de login, que não tem `INSERT` em `serviceaccount`.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool
from support_controller import Cleanup, connect, dsn


@pytest_asyncio.fixture
async def database_available() -> None:
    try:
        connection = await connect("ipm_serviceaccount_controller_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    manager = await connect("ipm_serviceaccount_manager_login")
    maintenance = await connect("ipm_maintenance_login")
    try:
        await manager.execute(
            "DELETE FROM ipm.serviceaccount WHERE resource_id = ANY(%s)", (tracker.resource_ids,)
        )
        for suffix in ("outbox", "operation", "action_result"):
            await maintenance.execute(
                f"DELETE FROM ipm.serviceaccount_{suffix} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabelas fixas)
                (tracker.resource_ids,),
            )
    finally:
        await manager.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def manager(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("ipm_serviceaccount_manager_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def outbox_reader(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Leitura do outbox com o papel do Publisher (o do Controller só insere nele)."""
    connection = await connect("ipm_serviceaccount_publisher_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def controller_pool(database_available: None) -> AsyncIterator[AsyncConnectionPool[Any]]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        dsn("ipm_serviceaccount_controller_login"),
        min_size=1,
        max_size=2,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    yield pool
    await pool.close()
