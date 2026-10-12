"""Fixtures: cliente HTTP do gateway, NATS e limpeza dos dados de teste."""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
MAILPIT_URL = os.environ.get("CONFORMANCE_MAILPIT_URL")
DATABASE_HOST = os.environ.get("CONFORMANCE_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CONFORMANCE_DATABASE_PORT", "5432")

MANAGER_LOGIN = "core_user_manager_login"
MAINTENANCE_LOGIN = "core_maintenance_login"
TABLE = 'core."user"'


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
        pytest.skip("CONFORMANCE_NATS_PASSWORD não definida")
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[NATS_URL], user="smarkee", password=NATS_PASSWORD, name="conformance"
    )
    yield client.jetstream()  # pyright: ignore[reportUnknownMemberType]
    await client.drain()


@pytest_asyncio.fixture
async def created(jetstream: JetStreamContext) -> AsyncIterator[list[str]]:
    """Identificadores criados pelo teste.

    Ao final, cada User é removido **pelo próprio loop** (pedido `delete`, Reconciler, Executor e
    Observer), para não deixar usuários no Zitadel. O que sobrar no SSOT é limpo diretamente.
    """
    resource_ids: list[str] = []
    yield resource_ids
    if not resource_ids:
        return
    for resource_id in resource_ids:
        await remove_through_the_loop(jetstream, resource_id)
    await _cleanup_database(resource_ids)


async def remove_through_the_loop(jetstream: JetStreamContext, resource_id: str) -> None:
    """Pede a remoção e espera o `updated` com `removed`. Sem `Ready` ou sem tempo, desiste."""
    subject = f"manager.updated.core.user.{resource_id}.changed"
    try:  # o usuário nunca chegou a ser aceito (por exemplo, e-mail duplicado): nada a remover
        await jetstream.get_last_msg("DESIRED", f"manager.desired.core.user.{resource_id}.changed")
    except Exception:
        return
    # Espera o loop convergir (Ready) antes de pedir a remoção; sem isso, o Executor poderia
    # criar o usuário no Zitadel depois do pedido de remoção.
    updated: dict[str, Any] = {}
    deadline = asyncio.get_running_loop().time() + 60.0
    while asyncio.get_running_loop().time() < deadline:
        try:
            updated = json.loads((await jetstream.get_last_msg("UPDATED", subject)).data or b"{}")
        except Exception:
            updated = {}
        if updated and (updated["data"].get("removed") or updated["data"]["phase"] == "Ready"):
            break
        await asyncio.sleep(0.5)
    if not updated or updated["data"].get("removed"):
        return
    now = datetime.now(UTC).isoformat()
    delete = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "core",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": "delete",
        "requestedBy": resource_id,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {
            "operationId": str(uuid.uuid7()),
            "requestDigest": "0" * 64,
            "resourceVersion": updated["data"]["resourceVersion"],
        },
    }
    await jetstream.publish(
        f"receiver.requested.core.user.{resource_id}.delete",
        json.dumps(delete).encode(),
        headers={"Nats-Msg-Id": delete["messageId"]},
    )
    deadline = asyncio.get_running_loop().time() + 40.0
    while asyncio.get_running_loop().time() < deadline:
        latest = json.loads((await jetstream.get_last_msg("UPDATED", subject)).data or b"{}")
        if latest["data"].get("removed"):
            return
        await asyncio.sleep(0.5)


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
