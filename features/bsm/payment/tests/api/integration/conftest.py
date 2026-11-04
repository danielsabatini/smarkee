"""Fixtures dos testes de integração da API: PostgreSQL de desenvolvimento, com os papéis reais.

Requer a stack de dev no ar (`infrastructure/dev`) e a migração de `bsm-payment`.
Sem o banco acessível, os testes são pulados. Os testes removem o que criam.
"""

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from support_api import DATABASE_HOST, DATABASE_PORT, connect

from bsm_payment.api.store.admission import SsotAdmissionStore
from bsm_payment.api.store.repository import SsotRepository
from bsm_payment.common.database import open_pool
from bsm_payment.common.settings import DatabaseSettings


@pytest_asyncio.fixture
async def api_conn() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    try:
        connection = await connect("bsm_payment_api_login")
    except psycopg.OperationalError as error:
        pytest.skip(f"PostgreSQL de dev indisponível: {error}")
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def cleanup(api_conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[list[str]]:
    resource_ids: list[str] = []
    yield resource_ids
    if not resource_ids:
        return
    controller = await connect("bsm_payment_controller_login")
    maintenance = await connect("bsm_maintenance_login")
    try:
        await controller.execute(
            "DELETE FROM bsm.payment WHERE resource_id = ANY(%s)", (resource_ids,)
        )
        await maintenance.execute(
            "DELETE FROM bsm.payment_outbox WHERE resource_id = ANY(%s)", (resource_ids,)
        )
        await maintenance.execute(
            "DELETE FROM bsm.payment_idempotency WHERE resource_id = ANY(%s)", (resource_ids,)
        )
    finally:
        await controller.close()
        await maintenance.close()


@pytest_asyncio.fixture
async def store(api_conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[SsotAdmissionStore]:
    pool = await open_pool(
        DatabaseSettings(
            host=DATABASE_HOST,
            port=int(DATABASE_PORT),
            user="bsm_payment_api_login",
            password=SecretStr("bsm_payment_api_login"),
        )
    )
    yield SsotAdmissionStore(pool)
    await pool.close()


@pytest_asyncio.fixture
async def repository(api_conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[SsotRepository]:
    pool = await open_pool(
        DatabaseSettings(
            host=DATABASE_HOST,
            port=int(DATABASE_PORT),
            user="bsm_payment_api_login",
            password=SecretStr("bsm_payment_api_login"),
        )
    )
    yield SsotRepository(pool)
    await pool.close()
