"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`) e a migração de `ipm-serviceaccount-manager`.
Sem o banco acessível, os testes são pulados. Os testes removem o que criam.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from support_receiver import DATABASE_HOST, DATABASE_PORT, connect

from ipm_serviceaccount.common.database import open_pool
from ipm_serviceaccount.receiver.settings import DatabaseSettings
from ipm_serviceaccount.receiver.store.repository import SsotRepository


@pytest_asyncio.fixture
async def manager() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    try:
        connection = await connect("ipm_serviceaccount_manager_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(manager: psycopg.AsyncConnection[Any]) -> AsyncIterator[list[str]]:
    resource_ids: list[str] = []
    yield resource_ids
    await manager.execute(
        "DELETE FROM ipm.serviceaccount WHERE resource_id = ANY(%s)", (resource_ids,)
    )
    maintenance = await connect("ipm_maintenance_login")
    try:
        for table in (
            "user_outbox",
            "user_operation",
            "user_action_result",
        ):
            await maintenance.execute(
                f"DELETE FROM ipm.{table} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabelas fixas)
                (resource_ids,),
            )
    finally:
        await maintenance.close()


@pytest_asyncio.fixture
async def repository(manager: psycopg.AsyncConnection[Any]) -> AsyncIterator[SsotRepository]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        name="ssot",
        user="ipm_serviceaccount_receiver_login",
        password=SecretStr("ipm_serviceaccount_receiver_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield SsotRepository(pool)
    await pool.close()
