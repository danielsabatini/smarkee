"""Fixtures de integração do Controller: PostgreSQL de desenvolvimento, com os papéis reais."""

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
        connection = await connect("bsm_payment_controller_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(database_available: None) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    yield tracker
    controller = await connect("bsm_payment_controller_login")
    maintenance = await connect("bsm_maintenance_login")
    try:
        if tracker.resource_ids:
            await controller.execute(
                "DELETE FROM bsm.payment WHERE resource_id = ANY(%s)", (tracker.resource_ids,)
            )
            await maintenance.execute(
                "DELETE FROM bsm.payment_outbox WHERE resource_id = ANY(%s)",
                (tracker.resource_ids,),
            )
    finally:
        await controller.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def api(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await connect("bsm_payment_api_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def outbox_reader(database_available: None) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Leitura do outbox com o papel do Publisher (o do Controller só insere nele)."""
    connection = await connect("bsm_payment_publisher_login")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def controller_pool(database_available: None) -> AsyncIterator[AsyncConnectionPool[Any]]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        dsn("bsm_payment_controller_login"),
        min_size=1,
        max_size=2,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    yield pool
    await pool.close()
