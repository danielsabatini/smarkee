"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`) e a migração `0011` de `core-account`.
Sem o banco acessível, os testes são pulados. Os testes removem o que criam.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from support_api import DATABASE_HOST, DATABASE_PORT, connect

from core_account.api.settings import DatabaseSettings
from core_account.api.store.repository import SsotRepository
from core_account.common.database import open_pool


@pytest_asyncio.fixture
async def api() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    try:
        connection = await connect("core_account_api_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(api: psycopg.AsyncConnection[Any]) -> AsyncIterator[list[str]]:
    resource_ids: list[str] = []
    yield resource_ids
    controller = await connect("core_account_controller_login")
    await controller.execute(
        "DELETE FROM core.account WHERE resource_id = ANY(%s)", (resource_ids,)
    )
    maintenance = await connect("core_maintenance_login")
    try:
        await maintenance.execute(
            "DELETE FROM core.account_idempotency WHERE requested_by LIKE 'test-%'"
        )
        for table in ("account_outbox",):
            await maintenance.execute(
                f"DELETE FROM core.{table} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabelas fixas)
                (resource_ids,),
            )
    finally:
        await controller.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def repository(api: psycopg.AsyncConnection[Any]) -> AsyncIterator[SsotRepository]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        name="ssot",
        user="core_account_api_login",
        password=SecretStr("core_account_api_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield SsotRepository(pool)
    await pool.close()
