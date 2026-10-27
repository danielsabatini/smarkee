"""Fixtures: gateway, NATS, a Organization de teste e a limpeza dos dados de teste."""

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
NATS_URL = os.environ.get("CONFORMANCE_MESSAGING_URL", "nats://localhost:4222")
NATS_PASSWORD = os.environ.get("CONFORMANCE_MESSAGING_PASSWORD")
ORGANIZATION_ID = os.environ.get("CONFORMANCE_ORGANIZATION_ID")
DATABASE_HOST = os.environ.get("CONFORMANCE_DATABASE_HOST", "localhost")
DATABASE_PORT = os.environ.get("CONFORMANCE_DATABASE_PORT", "5432")

MANAGER_LOGIN = "ipm_user_manager_login"
MAINTENANCE_LOGIN = "ipm_maintenance_login"
TABLE = "ipm.user"
DIGEST = "0" * 64


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=API_URL, headers={"Host": API_HOST}, timeout=10.0
    ) as client:
        yield client


@pytest.fixture
def organization_id() -> str:
    """Organization preparada pelo operador: Grant de `roles-ipm` e os papéis do Executor e do
    Observer nela (decisão 0077, `infrastructure/dev/README.md`). Sem ela, o loop é pulado."""
    if ORGANIZATION_ID is None:
        pytest.skip("CONFORMANCE_ORGANIZATION_ID não definida")
    return ORGANIZATION_ID


@pytest_asyncio.fixture
async def jetstream() -> AsyncIterator[JetStreamContext]:
    if NATS_PASSWORD is None:
        pytest.skip("CONFORMANCE_MESSAGING_PASSWORD não definida")
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[NATS_URL], user="smarkee", password=NATS_PASSWORD, name="conformance"
    )
    yield client.jetstream()  # pyright: ignore[reportUnknownMemberType]
    await client.drain()


def request(
    resource_id: str, operation: str, data: dict[str, Any], requested_by: str = "loop-user"
) -> dict[str, Any]:
    """Um `requested`, como o Receiver o publicaria."""
    now = datetime.now(UTC).isoformat()
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "ipm",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": operation,
        "requestedBy": requested_by,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {"operationId": str(uuid.uuid7()), "requestDigest": DIGEST, **data},
    }


async def send(jetstream: JetStreamContext, message: dict[str, Any]) -> None:
    subject = f"receiver.requested.ipm.user.{message['resourceId']}.{message['operation']}"
    await jetstream.publish(
        subject, json.dumps(message).encode(), headers={"Nats-Msg-Id": message["messageId"]}
    )


@pytest_asyncio.fixture
async def created(jetstream: JetStreamContext) -> AsyncIterator[list[str]]:
    """Identificadores criados pelo teste.

    Ao final, cada usuário é removido **pelo próprio loop** (pedido `delete` e Controller), para
    não deixar usuários no Zitadel. O que sobrar no SSOT é limpo diretamente.
    """
    resource_ids: list[str] = []
    yield resource_ids
    for resource_id in resource_ids:
        await remove_through_the_loop(jetstream, resource_id)
    if resource_ids:
        await _cleanup_database(resource_ids)


async def current_row(resource_id: str) -> dict[str, Any] | None:
    try:
        connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
            f" user={MANAGER_LOGIN} password={MANAGER_LOGIN} connect_timeout=3",
            autocommit=True,
        )
    except psycopg.OperationalError:
        return None
    try:
        cursor = await connection.execute(
            f"SELECT resource_version, lifecycle, desired, phase FROM {TABLE}"  # noqa: S608
            " WHERE resource_id = %s",
            (resource_id,),
        )
        row = await cursor.fetchone()
    finally:
        await connection.close()
    if row is None:
        return None
    return {"resource_version": row[0], "lifecycle": row[1], "desired": row[2], "phase": row[3]}


async def read_ssot(resource_id: str) -> dict[str, Any] | None:
    """Estado observado e `presence` do recurso no SSOT (a decisão 0096 extinguiu `observed`).

    `None` quando o registro não existe (removido) ou o SSOT de dev não está acessível.
    """
    try:
        connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
            f" user={MANAGER_LOGIN} password={MANAGER_LOGIN} connect_timeout=3",
            autocommit=True,
        )
    except psycopg.OperationalError:
        return None
    try:
        cursor = await connection.execute(
            f"SELECT presence, observed FROM {TABLE} WHERE resource_id = %s",  # noqa: S608
            (resource_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {"presence": row[0], "data": row[1] or {}}
    finally:
        await connection.close()


async def remove_through_the_loop(jetstream: JetStreamContext, resource_id: str) -> None:
    """Pede a remoção (tirando a proteção antes, se houver) e espera o registro sumir do SSOT."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 60.0
    row = await current_row(resource_id)
    while row is not None and row["phase"] not in ("Ready", "Failed") and loop.time() < deadline:
        await asyncio.sleep(0.5)  # espera o loop convergir antes de pedir a remoção
        row = await current_row(resource_id)
    if row is None or row["lifecycle"] == "absent":
        return
    version = str(row["resource_version"])
    if row["desired"].get("deletionProtection") is True:
        await send(
            jetstream,
            request(
                resource_id,
                "update",
                {"resourceVersion": version, "specification": {"deletionProtection": False}},
            ),
        )
        while loop.time() < deadline:
            row = await current_row(resource_id)
            if row is not None and row["desired"].get("deletionProtection") is False:
                version = str(row["resource_version"])
                break
            await asyncio.sleep(0.3)
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    while loop.time() < deadline and await current_row(resource_id) is not None:
        await asyncio.sleep(0.5)


async def _cleanup_database(resource_ids: list[str]) -> None:
    def dsn(login: str) -> str:
        return (
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
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
                f"DELETE FROM {TABLE}_{suffix}"  # noqa: S608
                " WHERE resource_id = ANY(%s)",
                (resource_ids,),
            )
    finally:
        await manager.close()
        await maintenance.close()
