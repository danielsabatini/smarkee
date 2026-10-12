"""Fixtures: cliente HTTP do gateway, NATS e limpeza dos dados de teste."""

import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import nats
import psycopg
import pytest
import pytest_asyncio
from nats.js import JetStreamContext

API_URL = os.environ.get("CONFORMANCE_API_URL", "http://localhost:8080")
API_HOST = os.environ.get("CONFORMANCE_API_HOST", "api-dev.smarkee.com.br")
NATS_URL = os.environ.get("CONFORMANCE_NATS_URL", "nats://localhost:4222")
NATS_PASSWORD = os.environ.get("CONFORMANCE_NATS_PASSWORD")
ACCESS_TOKEN = os.environ.get("CONFORMANCE_ACCESS_TOKEN")
DATABASE_HOST = os.environ.get("CONFORMANCE_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CONFORMANCE_DATABASE_PORT", "5432")

MANAGER_LOGIN = "ipm_organization_manager_login"
MAINTENANCE_LOGIN = "ipm_maintenance_login"
TABLE = "ipm.organization"


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=API_URL, headers={"Host": API_HOST}, timeout=10.0
    ) as client:
        yield client


@pytest.fixture
def authorization() -> dict[str, str]:
    if ACCESS_TOKEN is None:
        pytest.skip("CONFORMANCE_ACCESS_TOKEN não definida")
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


@pytest_asyncio.fixture
async def jetstream() -> AsyncIterator[JetStreamContext]:
    if NATS_PASSWORD is None:
        pytest.skip("CONFORMANCE_NATS_PASSWORD não definida")
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[NATS_URL], user="smarkee", password=NATS_PASSWORD, name="conformance"
    )
    yield client.jetstream()  # pyright: ignore[reportUnknownMemberType]
    await client.drain()


@pytest_asyncio.fixture
async def created() -> AsyncIterator[list[str]]:
    """Identificadores criados pelo teste; removidos do SSOT e do transporte ao final."""
    resource_ids: list[str] = []
    yield resource_ids
    if not resource_ids:
        return
    await _cleanup_database(resource_ids)


async def _cleanup_database(resource_ids: list[str]) -> None:
    def dsn(login: str) -> str:
        return (
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=smarkee"
            f" user={login} password={login} connect_timeout=3"
        )

    try:
        manager: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            dsn(MANAGER_LOGIN), autocommit=True
        )
        maintenance: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            dsn(MAINTENANCE_LOGIN), autocommit=True
        )
    except psycopg.OperationalError:
        return  # sem acesso ao SSOT de dev: a limpeza é opcional
    try:
        await manager.execute(
            f"DELETE FROM {TABLE} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabela fixa)
            (resource_ids,),
        )
        for suffix in ("outbox", "operation", "action_result"):
            await maintenance.execute(
                f"DELETE FROM {TABLE.replace('"user"', 'user')}_{suffix}"  # noqa: S608
                " WHERE resource_id = ANY(%s)",
                (resource_ids,),
            )
    finally:
        await manager.close()
        await maintenance.close()
