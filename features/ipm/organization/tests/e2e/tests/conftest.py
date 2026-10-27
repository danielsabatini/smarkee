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
NATS_URL = os.environ.get("CONFORMANCE_MESSAGING_URL", "nats://localhost:4222")
NATS_PASSWORD = os.environ.get("CONFORMANCE_MESSAGING_PASSWORD")
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
        pytest.skip("CONFORMANCE_MESSAGING_PASSWORD não definida")
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[NATS_URL], user="smarkee", password=NATS_PASSWORD, name="conformance"
    )
    yield client.jetstream()  # pyright: ignore[reportUnknownMemberType]
    await client.drain()


@pytest_asyncio.fixture
async def created(jetstream: JetStreamContext) -> AsyncIterator[list[str]]:
    """Identificadores criados pelo teste.

    Ao final, cada Organization é removida **pelo próprio loop** (pedido `delete`, Reconciler,
    Executor e Observer), para não deixar organizações no Zitadel. O que sobrar no SSOT é limpo
    diretamente.
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
    subject = f"manager.updated.ipm.organization.{resource_id}.changed"
    try:  # a organização nunca chegou a ser aceita (por exemplo, nome duplicado): nada a remover
        await jetstream.get_last_msg(
            "DESIRED", f"manager.desired.ipm.organization.{resource_id}.changed"
        )
    except Exception:
        return
    # Espera o loop convergir (Ready) antes de pedir a remoção; sem isso, o Executor poderia
    # criar a organização no Zitadel depois do pedido de remoção.
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
    version = await unprotect_through_the_loop(
        jetstream, resource_id, updated["data"]["resourceVersion"]
    )
    now = datetime.now(UTC).isoformat()
    delete = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "ipm",
        "resourceType": "organization",
        "resourceId": resource_id,
        "operation": "delete",
        "requestedBy": "conformance-user",
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {
            "operationId": str(uuid.uuid7()),
            "requestDigest": "0" * 64,
            "resourceVersion": version,
        },
    }
    await jetstream.publish(
        f"receiver.requested.ipm.organization.{resource_id}.delete",
        json.dumps(delete).encode(),
        headers={"Nats-Msg-Id": delete["messageId"]},
    )
    deadline = asyncio.get_running_loop().time() + 40.0
    while asyncio.get_running_loop().time() < deadline:
        latest = json.loads((await jetstream.get_last_msg("UPDATED", subject)).data or b"{}")
        if latest["data"].get("removed"):
            return
        await asyncio.sleep(0.5)


async def unprotect_through_the_loop(
    jetstream: JetStreamContext, resource_id: str, resource_version: str
) -> str:
    """Pede o `update` que tira a proteção contra exclusão e devolve a versão seguinte.

    A proteção percorre o loop como qualquer alteração (decisão 0072): conclui quando o Manager
    confirma a nova geração (`observed_generation = desired_generation`). A versão nova vem do SSOT.
    Sem acesso ao SSOT, devolve a versão recebida e o `delete` segue por conta e risco.
    """
    now = datetime.now(UTC).isoformat()
    update = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "ipm",
        "resourceType": "organization",
        "resourceId": resource_id,
        "operation": "update",
        "requestedBy": "conformance-user",
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {
            "operationId": str(uuid.uuid7()),
            "requestDigest": "0" * 64,
            "resourceVersion": resource_version,
            "specification": {"deletionProtection": False},
        },
    }
    await jetstream.publish(
        f"receiver.requested.ipm.organization.{resource_id}.update",
        json.dumps(update).encode(),
        headers={"Nats-Msg-Id": update["messageId"]},
    )
    try:
        connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
            f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
            f" user={MANAGER_LOGIN} password={MANAGER_LOGIN} connect_timeout=3",
            autocommit=True,
        )
    except psycopg.OperationalError:
        return resource_version
    try:
        deadline = asyncio.get_running_loop().time() + 40.0
        while asyncio.get_running_loop().time() < deadline:
            cursor = await connection.execute(
                f"SELECT resource_version FROM {TABLE} WHERE resource_id = %s"  # noqa: S608
                " AND (desired->>'deletionProtection')::boolean IS FALSE"
                " AND observed_generation = desired_generation",
                (resource_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                return str(row[0])
            await asyncio.sleep(0.3)
    finally:
        await connection.close()
    return resource_version


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


async def operation_statuses(resource_id: str) -> list[str]:
    """Estados das Operations do recurso, da mais antiga à mais nova."""
    connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
        f"host={DATABASE_HOST} port={DATABASE_PORT} dbname=ssot"
        f" user={MANAGER_LOGIN} password={MANAGER_LOGIN} connect_timeout=3",
        autocommit=True,
    )
    try:
        cursor = await connection.execute(
            f"SELECT operation_status FROM {TABLE}_operation WHERE resource_id = %s"  # noqa: S608
            " ORDER BY created_at",
            (resource_id,),
        )
        return [str(row[0]) for row in await cursor.fetchall()]
    finally:
        await connection.close()


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
