"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`) e a migração de `core-organization-manager`.
Sem o banco acessível, os testes são pulados. Os testes removem o que criam.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from support import DATABASE_HOST, DATABASE_PORT, connect

from core_user_receiver.settings import DatabaseSettings
from core_user_receiver.store.database import open_pool
from core_user_receiver.store.repository import PostgresRepository


@pytest_asyncio.fixture
async def manager() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    try:
        connection = await connect("core_user_manager_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(manager: psycopg.AsyncConnection[Any]) -> AsyncIterator[list[str]]:
    resource_ids: list[str] = []
    yield resource_ids
    await manager.execute('DELETE FROM core."user" WHERE resource_id = ANY(%s)', (resource_ids,))
    maintenance = await connect("core_maintenance_login")
    try:
        for table in (
            "user_outbox",
            "user_operation",
            "user_action_result",
        ):
            await maintenance.execute(
                f"DELETE FROM core.{table} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabelas fixas)
                (resource_ids,),
            )
    finally:
        await maintenance.close()


@pytest_asyncio.fixture
async def repository(manager: psycopg.AsyncConnection[Any]) -> AsyncIterator[PostgresRepository]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        password=SecretStr("core_user_receiver_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield PostgresRepository(pool)
    await pool.close()
