"""Fixtures dos testes de integração: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`) e a migração de `bsm-account-api`.
Sem o banco acessível, os testes são pulados. Os testes removem o que criam.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from support_api import DATABASE_HOST, DATABASE_PORT, connect

from bsm_account.api.store.admission import SsotAdmissionStore
from bsm_account.api.store.repository import SsotRepository
from bsm_account.common.database import open_pool
from bsm_account.common.settings import DatabaseSettings


@pytest_asyncio.fixture
async def api_conn() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    try:
        connection = await connect("bsm_account_api_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(api_conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[list[str]]:
    resource_ids: list[str] = []
    yield resource_ids
    if resource_ids:
        await api_conn.execute(
            "DELETE FROM bsm.account WHERE resource_id = ANY(%s)", (resource_ids,)
        )
        try:
            maintenance = await connect("bsm_maintenance_login")
            try:
                for table in ("account_outbox", "account_idempotency"):
                    await maintenance.execute(
                        f"DELETE FROM bsm.{table} WHERE resource_id = ANY(%s)",  # noqa: S608
                        (resource_ids,),
                    )
            finally:
                await maintenance.close()
        except psycopg.OperationalError:
            pass


@pytest_asyncio.fixture
async def repository(api_conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[SsotRepository]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        name="ssot",
        user="bsm_account_api_login",
        password=SecretStr("bsm_account_api_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield SsotRepository(pool)
    await pool.close()


@pytest_asyncio.fixture
async def store(api_conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[SsotAdmissionStore]:
    settings = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        name="ssot",
        user="bsm_account_api_login",
        password=SecretStr("bsm_account_api_login"),
    )
    pool = await open_pool(settings, max_size=2)
    yield SsotAdmissionStore(pool)
    await pool.close()
