"""Loop completo de ipm.permission (Receiver até Observer), com os componentes reais e o Zitadel.

Usa os componentes reais e o Zitadel de dev. Os pedidos entram direto no NATS, como o Receiver os
publicaria; cada Permission é removida pelo próprio loop ao final (fixture `created`).
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import unprotect_through_the_loop
from contracts import assert_valid
from nats.js import JetStreamContext

DIGEST = "0" * 64
READY_SECONDS = 60.0


def subject_of(kind: str, resource_id: str) -> tuple[str, str]:
    """Stream e Subject da última mensagem de cada tipo do recurso."""
    return {
        "desired": ("DESIRED", f"manager.desired.ipm.permission.{resource_id}.changed"),
        "observed": ("OBSERVED", f"observer.observed.ipm.permission.{resource_id}.changed"),
        "updated": ("UPDATED", f"manager.updated.ipm.permission.{resource_id}.changed"),
    }[kind]


async def last(
    jetstream: JetStreamContext, kind: str, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    stream, subject = subject_of(kind, resource_id)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return json.loads((await jetstream.get_last_msg(stream, subject)).data or b"{}")
        except Exception:
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.3)


async def wait_for(
    jetstream: JetStreamContext,
    kind: str,
    resource_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = READY_SECONDS,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        message = await last(jetstream, kind, resource_id, timeout=timeout)
        if predicate(message):
            return message
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"{kind}: condição não atendida: {message}")
        await asyncio.sleep(0.5)


async def ready_after(
    jetstream: JetStreamContext, resource_id: str, version: str
) -> dict[str, Any]:
    """Espera o `Ready` de uma versão posterior à do pedido e que a versão pare de mudar."""
    current = await wait_for(
        jetstream,
        "updated",
        resource_id,
        lambda m: (
            m["data"]["phase"] == "Ready" and int(m["data"]["resourceVersion"]) > int(version)
        ),
    )
    while True:
        await asyncio.sleep(1.5)
        latest = await last(jetstream, "updated", resource_id)
        if latest["data"]["resourceVersion"] == current["data"]["resourceVersion"]:
            return latest
        current = latest


def request(
    resource_id: str, operation: str, data: dict[str, Any], requested_by: str = "loop-user"
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "ipm",
        "resourceType": "permission",
        "resourceId": resource_id,
        "operation": operation,
        "requestedBy": requested_by,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {"operationId": str(uuid.uuid7()), "requestDigest": DIGEST, **data},
    }


async def send(jetstream: JetStreamContext, message: dict[str, Any]) -> None:
    subject = f"receiver.requested.ipm.permission.{message['resourceId']}.{message['operation']}"
    await jetstream.publish(
        subject, json.dumps(message).encode(), headers={"Nats-Msg-Id": message["messageId"]}
    )


async def create_ready(
    jetstream: JetStreamContext,
    created: list[str],
    name: str,
    description: str = "Loop test permission",
) -> tuple[str, dict[str, Any]]:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    await send(
        jetstream,
        request(
            resource_id,
            "create",
            {
                "specification": {
                    "name": name,
                    "description": description,
                    "grantable": True,
                }
            },
        ),
    )
    updated = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"]["phase"] == "Ready"
    )
    return resource_id, updated


async def test_the_whole_loop_creates_updates_and_removes_the_permission(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    perm_name = f"bsm.e2e.p{uuid.uuid4().hex[:7]}"

    # 1. Criação: o loop converge até Ready, com a role criada no Zitadel (roles-bsm).
    resource_id, updated = await create_ready(jetstream, created, perm_name, "Permissao inicial")
    assert_valid("common/updated.v1.schema.json", updated["data"])
    observed = await last(jetstream, "observed", resource_id)
    assert observed["presence"] == "present"
    assert_valid("ipm/permission/observed.v1.schema.json", observed["data"])
    assert observed["data"] == {
        "name": perm_name,
        "description": "Permissao inicial",
        "group": "bsm",
    }
    raw = await jetstream.get_last_msg(
        "RESULT", f"executor.completed.ipm.permission.{resource_id}.create"
    )
    completed = json.loads(raw.data or b"{}")
    assert_valid("common/message-envelope.v1.schema.json", completed)
    assert completed["actionId"].startswith(f"{resource_id}.1.create.")

    # 2. Atualização: alterar a descrição.
    new_description = "Permissao atualizada pelo teste"
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {
                "resourceVersion": updated["data"]["resourceVersion"],
                "specification": {"description": new_description},
            },
        ),
    )
    await wait_for(
        jetstream,
        "observed",
        resource_id,
        lambda m: m["data"].get("description") == new_description,
    )
    updated = await ready_after(jetstream, resource_id, updated["data"]["resourceVersion"])

    # 3. Proteção contra exclusão: remoção rejeitada enquanto deletionProtection = true.
    version = updated["data"]["resourceVersion"]
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    await asyncio.sleep(3.0)
    assert not (await last(jetstream, "updated", resource_id))["data"].get("removed")

    # 4. Desproteger e remover: Executor remove role no Zitadel, Observer confirma ausência.
    version = await unprotect_through_the_loop(jetstream, resource_id, version)
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    removed = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"].get("removed") is True
    )
    assert removed["data"]["removed"] is True
    absent = await last(jetstream, "observed", resource_id)
    assert (absent["presence"], absent["data"]) == ("absent", {})


async def test_a_name_already_used_never_reaches_the_provider(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    perm_name = f"bsm.e2e.p{uuid.uuid4().hex[:7]}"
    first, _ = await create_ready(jetstream, created, perm_name)

    second = str(uuid.uuid7())
    created.append(second)
    await send(
        jetstream,
        request(
            second,
            "create",
            {
                "specification": {
                    "name": perm_name,
                    "description": "Permissao duplicada",
                    "grantable": True,
                }
            },
        ),
    )
    await asyncio.sleep(3.0)
    with pytest.raises(Exception, match=r"no message found|not found"):
        await jetstream.get_last_msg("DESIRED", subject_of("desired", second)[1])
    assert first != second
