"""Fixtures de integração do Controller: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar com a migração `0007-permission-controller`. Sem o banco acessível,
os testes são pulados. O recurso é criado pela API (como a admissão faria) e o Controller roda com
o próprio papel de login, que não tem `INSERT` em `permission`.
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
        connection = await connect("ipm_permission_controller_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    controller = await connect("ipm_permission_controller_login")
    maintenance = await connect("ipm_maintenance_login")
    try:
        await controller.execute(
            "DELETE FROM ipm.permission WHERE resource_id = ANY(%s)", (tracker.resource_ids,)
        )
        await maintenance.execute(
            "DELETE FROM ipm.permission_outbox WHERE resource_id = ANY(%s)",
            (tracker.resource_ids,),
        )
    finally:
        await controller.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def api(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("ipm_permission_api_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def outbox_reader(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Leitura do outbox com o papel do Publisher (o do Controller só insere nele)."""
    connection = await connect("ipm_permission_publisher_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def controller_pool(database_available: None) -> AsyncIterator[AsyncConnectionPool[Any]]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        dsn("ipm_permission_controller_login"),
        min_size=1,
        max_size=2,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    yield pool
    await pool.close()
