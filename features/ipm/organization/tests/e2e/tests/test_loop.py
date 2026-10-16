"""Loop completo de ipm.organization (Receiver até Observer), com os componentes reais e o Zitadel.

Usa os componentes reais e o Zitadel de dev. Os pedidos entram direto no NATS, como o Receiver os
publicaria; cada Organization é removida pelo próprio loop ao final (fixture `created`).
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from contracts import assert_valid
from nats.js import JetStreamContext

DIGEST = "0" * 64
READY_SECONDS = 60.0


def subject_of(kind: str, resource_id: str) -> tuple[str, str]:
    """Stream e Subject da última mensagem de cada tipo do recurso."""
    return {
        "desired": ("DESIRED", f"manager.desired.ipm.organization.{resource_id}.changed"),
        "observed": ("OBSERVED", f"observer.observed.ipm.organization.{resource_id}.changed"),
        "updated": ("UPDATED", f"manager.updated.ipm.organization.{resource_id}.changed"),
    }[kind]


async def last(
    jetstream: JetStreamContext, kind: str, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    stream, subject = subject_of(kind, resource_id)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return json.loads((await jetstream.get_last_msg(stream, subject)).data or b"{}")
        except Exception:  # ainda não publicado: tenta de novo até o prazo
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
    """Espera o `Ready` de uma versão **posterior** à do pedido e que a versão pare de mudar.

    O anterior já era `Ready`, e o Manager ainda grava o resultado e a observação seguintes: um
    cliente real lê a versão atual antes de cada alteração, e é isso que o teste imita.
    """
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
        "resourceType": "organization",
        "resourceId": resource_id,
        "operation": operation,
        "requestedBy": requested_by,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {"operationId": str(uuid.uuid7()), "requestDigest": DIGEST, **data},
    }


async def send(jetstream: JetStreamContext, message: dict[str, Any]) -> None:
    subject = f"receiver.requested.ipm.organization.{message['resourceId']}.{message['operation']}"
    await jetstream.publish(
        subject, json.dumps(message).encode(), headers={"Nats-Msg-Id": message["messageId"]}
    )


async def create_ready(
    jetstream: JetStreamContext, created: list[str], name: str
) -> tuple[str, dict[str, Any]]:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    await send(
        jetstream,
        request(
            resource_id, "create", {"specification": {"name": name, "platformAccess": "granted"}}
        ),
    )
    updated = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"]["phase"] == "Ready"
    )
    return resource_id, updated


async def test_the_whole_loop_creates_updates_and_removes_the_organization(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    name = "loop-" + uuid.uuid4().hex[:10]

    # 1. Criação: o loop converge sozinho até Ready, com a organização criada no Zitadel.
    resource_id, updated = await create_ready(jetstream, created, name)
    assert_valid("common/updated.v1.schema.json", updated["data"])
    observed = await last(jetstream, "observed", resource_id)
    assert observed["presence"] == "present"
    assert_valid("ipm/organization/observed.v1.schema.json", observed["data"])
    assert observed["data"] == {
        "name": name,
        "platformAccess": "granted",
        "organizationState": "active",
    }
    raw = await jetstream.get_last_msg(
        "RESULT", f"executor.completed.ipm.organization.{resource_id}.create"
    )
    completed = json.loads(raw.data or b"{}")
    assert_valid("common/message-envelope.v1.schema.json", completed)
    assert completed["actionId"].startswith(f"{resource_id}.1.create.")

    # 2. Renomear: o Executor renomeia a organização e o Observer lê o nome novo.
    renamed = name + "-b"
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {
                "resourceVersion": updated["data"]["resourceVersion"],
                "specification": {"name": renamed},
            },
        ),
    )
    await wait_for(jetstream, "observed", resource_id, lambda m: m["data"].get("name") == renamed)
    updated = await ready_after(jetstream, resource_id, updated["data"]["resourceVersion"])

    # 3. `platformAccess` revoked desativa a organização; granted a ativa de novo.
    for access, state in (("revoked", "inactive"), ("granted", "active")):
        await send(
            jetstream,
            request(
                resource_id,
                "update",
                {
                    "resourceVersion": updated["data"]["resourceVersion"],
                    "specification": {"platformAccess": access},
                },
                requested_by="operator",
            ),
        )
        await wait_for(
            jetstream,
            "observed",
            resource_id,
            lambda m, state=state: m["data"].get("organizationState") == state,
        )
        updated = await ready_after(jetstream, resource_id, updated["data"]["resourceVersion"])

    # 4. Remoção: o Executor remove a organização, o Observer confirma a ausência e o Manager
    # apaga o registro (`removed`).
    await send(
        jetstream,
        request(resource_id, "delete", {"resourceVersion": updated["data"]["resourceVersion"]}),
    )
    removed = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"].get("removed") is True
    )
    assert removed["data"]["removed"] is True
    absent = await last(jetstream, "observed", resource_id)
    assert (absent["presence"], absent["data"]) == ("absent", {})


async def test_a_name_already_used_never_reaches_the_provider(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    name = "dup-" + uuid.uuid4().hex[:10]
    first, _ = await create_ready(jetstream, created, name)

    second = str(uuid.uuid7())
    created.append(second)
    await send(
        jetstream,
        request(second, "create", {"specification": {"name": name, "platformAccess": "granted"}}),
    )
    await asyncio.sleep(3.0)

    with pytest.raises(Exception, match=r"no message found|not found"):
        await jetstream.get_last_msg("DESIRED", subject_of("desired", second)[1])
    assert first != second


async def test_a_reserved_name_never_reaches_the_provider(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    await send(
        jetstream,
        request(
            resource_id,
            "create",
            {"specification": {"name": "zitadel", "platformAccess": "granted"}},
        ),
    )
    await asyncio.sleep(3.0)

    with pytest.raises(Exception, match=r"no message found|not found"):
        await jetstream.get_last_msg("DESIRED", subject_of("desired", resource_id)[1])
