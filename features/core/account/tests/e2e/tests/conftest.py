"""Fixtures: cliente HTTP do gateway, NATS, SSOT e limpeza dos dados de teste."""

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
MAILPIT_URL = os.environ.get("CONFORMANCE_MAILPIT_URL")
DATABASE_HOST = os.environ.get("CONFORMANCE_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CONFORMANCE_DATABASE_PORT", "5432")

CONTROLLER_LOGIN = "core_account_controller_login"  # lê o SSOT e apaga o recurso (decisão 0096)
MAINTENANCE_LOGIN = "core_maintenance_login"
TABLE = "core.account"


MAXIMUM_RATE_LIMIT_RETRIES = 3


class RetryAfterTransport(httpx.AsyncBaseTransport):
    """Repete (até 3 vezes) o pedido recusado pelo limite de taxa (429), após o `Retry-After`.

    O gateway limita o cadastro anônimo a 10 por minuto por IP; a suíte completa, com os testes de
    caos, passa desse limite. Os testes de contrato não dependem do limite.
    """

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        for _ in range(MAXIMUM_RATE_LIMIT_RETRIES):
            if response.status_code != 429:
                break
            await response.aclose()
            await asyncio.sleep(min(float(response.headers.get("retry-after", "30")), 65.0))
            response = await self._inner.handle_async_request(request)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=API_URL,
        headers={"Host": API_HOST},
        timeout=10.0,
        transport=RetryAfterTransport(),
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
        pytest.skip("CONFORMANCE_MESSAGING_PASSWORD não definida")
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[NATS_URL], user="smarkee", password=NATS_PASSWORD, name="conformance"
    )
    yield client.jetstream()  # pyright: ignore[reportUnknownMemberType]
    await client.drain()


@pytest.fixture
def headers() -> dict[str, str]:
    """Token de um operador: lê qualquer conta e altera a proteção contra exclusão (0098)."""
    if ACCESS_TOKEN is None:
        pytest.skip("CONFORMANCE_ACCESS_TOKEN não definida")
    return {"Authorization": f"Bearer {ACCESS_TOKEN}"}


@pytest_asyncio.fixture
async def created() -> AsyncIterator[list[str]]:
    """Identificadores criados pelo teste, removidos ao final.

    A exclusão pela API só é aceita para a própria conta (`ResourcesNotVerifiable`, decisão 0100):
    o token do operador não a alcança. Por isso a limpeza tira a proteção pela API (se houver token)
    e apaga o registro direto no SSOT. O usuário no Zitadel é limpo por `scripts/dev/cleanup`.
    """
    resource_ids: list[str] = []
    yield resource_ids
    if resource_ids:
        await _cleanup_database(resource_ids)


async def connect(login: str) -> psycopg.AsyncConnection[Any] | None:
    try:
        return await psycopg.AsyncConnection.connect(
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
            f" user={login} password={login} connect_timeout=3",
            autocommit=True,
        )
    except psycopg.OperationalError:
        return None  # sem acesso ao SSOT de dev


async def read_ssot(resource_id: str) -> dict[str, Any] | None:
    """Estado do recurso no SSOT: `presence`, `observed` (gravado pelo Controller), fase e desired.

    `None` quando o registro não existe (removido) ou o SSOT de dev não está acessível.
    """
    connection = await connect(CONTROLLER_LOGIN)
    if connection is None:
        return None
    try:
        cursor = await connection.execute(
            "SELECT presence, observed, phase, lifecycle, desired, resource_version"  # noqa: S608
            f" FROM {TABLE} WHERE resource_id = %s",
            (resource_id,),
        )
        row = await cursor.fetchone()
    finally:
        await connection.close()
    if row is None:
        return None
    return {
        "presence": row[0],
        "data": row[1] or {},
        "phase": row[2],
        "lifecycle": row[3],
        "desired": row[4],
        "resource_version": row[5],
    }


async def _cleanup_database(resource_ids: list[str]) -> None:
    controller = await connect(CONTROLLER_LOGIN)
    maintenance = await connect(MAINTENANCE_LOGIN)
    if controller is None or maintenance is None:
        return  # sem acesso ao SSOT de dev: a limpeza é opcional
    try:
        await controller.execute(
            f"DELETE FROM {TABLE} WHERE resource_id = ANY(%s)",  # noqa: S608 (tabela fixa)
            (resource_ids,),
        )
        await maintenance.execute(
            f"DELETE FROM {TABLE}_outbox WHERE resource_id = ANY(%s)",  # noqa: S608 (tabela fixa)
            (resource_ids,),
        )
    finally:
        await controller.close()
        await maintenance.close()
