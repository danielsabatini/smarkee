"""Fixtures: gateway, NATS e a limpeza dos dados de teste."""

import asyncio
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
NATS_URL = os.environ.get("CONFORMANCE_MESSAGING_URL", "nats://localhost:4222")
NATS_PASSWORD = os.environ.get("CONFORMANCE_MESSAGING_PASSWORD")
ACCESS_TOKEN = os.environ.get("CONFORMANCE_ACCESS_TOKEN")
DATABASE_HOST = os.environ.get("CONFORMANCE_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CONFORMANCE_DATABASE_PORT", "5432")

API_LOGIN = "ipm_group_api_login"  # a API apaga a linha (decisão 0098)
MAINTENANCE_LOGIN = "ipm_maintenance_login"
TABLE = "ipm.group"


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=API_URL, headers={"Host": API_HOST}, timeout=10.0
    ) as client:
        yield client


@pytest.fixture
def headers() -> dict[str, str]:
    """Token de um operador (age em qualquer Organization): a API é a porta de entrada (0098)."""
    if not ACCESS_TOKEN:
        pytest.skip("CONFORMANCE_ACCESS_TOKEN não definida")
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


@pytest_asyncio.fixture
async def jetstream() -> AsyncIterator[JetStreamContext]:
    if not NATS_PASSWORD:
        pytest.skip("CONFORMANCE_MESSAGING_PASSWORD não definida")
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[NATS_URL], user="smarkee", password=NATS_PASSWORD, name="conformance"
    )
    yield client.jetstream()  # pyright: ignore[reportUnknownMemberType]
    await client.drain()


@pytest_asyncio.fixture
async def created(api: httpx.AsyncClient, headers: dict[str, str]) -> AsyncIterator[list[str]]:
    """Identificadores criados pelo teste.

    Ao final, cada Grupo é removido **pela própria API** (`DELETE`, tirando antes a proteção). O que
    sobrar no SSOT é limpo diretamente.
    """
    resource_ids: list[str] = []
    yield resource_ids
    for resource_id in resource_ids:
        await remove_through_the_api(api, headers, resource_id)
    if resource_ids:
        await _cleanup_database(resource_ids)


async def current_row(resource_id: str) -> dict[str, Any] | None:
    try:
        connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
            f" user={API_LOGIN} password={API_LOGIN} connect_timeout=3",
            autocommit=True,
        )
    except psycopg.OperationalError:
        return None
    try:
        cursor = await connection.execute(
            f"SELECT resource_version, desired FROM {TABLE}"  # noqa: S608 (tabela fixa)
            " WHERE resource_id = %s",
            (resource_id,),
        )
        row = await cursor.fetchone()
    finally:
        await connection.close()
    if row is None:
        return None
    return {"resource_version": row[0], "desired": row[1]}


async def remove_through_the_api(
    api: httpx.AsyncClient, headers: dict[str, str], resource_id: str
) -> None:
    """Tira a proteção (se houver) e apaga o Grupo pela API; a remoção é síncrona (0098)."""
    row = await current_row(resource_id)
    if row is None:
        return
    version = str(row["resource_version"])
    path = f"/v1/ipm/groups/{resource_id}"
    if row["desired"].get("deletionProtection") is not False:
        unprotected = await api.patch(
            path, json={"resourceVersion": version, "deletionProtection": False}, headers=headers
        )
        if unprotected.status_code == 200:
            version = unprotected.json()["resourceVersion"]
    await api.delete(path, params={"resourceVersion": version}, headers=headers)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0
    while loop.time() < deadline and await current_row(resource_id) is not None:
        await asyncio.sleep(0.3)


async def _cleanup_database(resource_ids: list[str]) -> None:
    def dsn(login: str) -> str:
        return (
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
            f" user={login} password={login} connect_timeout=3"
        )

    try:
        api: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            dsn(API_LOGIN), autocommit=True
        )
        maintenance: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            dsn(MAINTENANCE_LOGIN), autocommit=True
        )
    except psycopg.OperationalError:
        return  # sem acesso ao SSOT de dev: a limpeza é opcional
    try:
        await api.execute(
            f"DELETE FROM {TABLE} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabela fixa)
            (resource_ids,),
        )
        await maintenance.execute(
            f"DELETE FROM {TABLE}_outbox WHERE resource_id = ANY(%s)",  # noqa: S608
            (resource_ids,),
        )
    finally:
        await api.close()
        await maintenance.close()
