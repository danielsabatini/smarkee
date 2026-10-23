"""Loop completo de bsm.account (Receiver até Observer), com os componentes reais.

Usa os componentes reais. Os pedidos entram direto no NATS, como o Receiver os publicaria; cada
Billing Account é removida pelo próprio loop ao final (fixture `created`).
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
        "desired": ("DESIRED", f"manager.desired.bsm.account.{resource_id}.changed"),
        "observed": ("OBSERVED", f"observer.observed.bsm.account.{resource_id}.changed"),
        "updated": ("UPDATED", f"manager.updated.bsm.account.{resource_id}.changed"),
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
    """Espera o `Ready` de uma versão **posterior** à do pedido e que a versão pare de mudar."""
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
        "module": "bsm",
        "resourceType": "account",
        "resourceId": resource_id,
        "operation": operation,
        "requestedBy": requested_by,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {"operationId": str(uuid.uuid7()), "requestDigest": DIGEST, **data},
    }


async def send(jetstream: JetStreamContext, message: dict[str, Any]) -> None:
    subject = f"receiver.requested.bsm.account.{message['resourceId']}.{message['operation']}"
    await jetstream.publish(
        subject, json.dumps(message).encode(), headers={"Nats-Msg-Id": message["messageId"]}
    )


async def create_ready(
    jetstream: JetStreamContext, created: list[str], display_name: str
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
                    "displayName": display_name,
                    "billingCurrency": "BRL",
                    "billingContacts": ["finops@acme.com.br"],
                }
            },
        ),
    )
    updated = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"]["phase"] == "Ready"
    )
    return resource_id, updated


async def test_the_whole_loop_creates_updates_and_removes_the_account(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    display_name = "Loop " + uuid.uuid4().hex[:10]

    # 1. Criação: o loop converge sozinho até Ready, com a conta gravada no estado local.
    resource_id, updated = await create_ready(jetstream, created, display_name)
    assert_valid("common/updated.v1.schema.json", updated["data"])
    observed = await last(jetstream, "observed", resource_id)
    assert observed["presence"] == "present"
    assert_valid("bsm/account/observed.v1.schema.json", observed["data"])
    assert observed["data"] == {
        "displayName": display_name,
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.com.br"],
        "deletionProtection": True,
    }
    raw = await jetstream.get_last_msg(
        "RESULT", f"executor.completed.bsm.account.{resource_id}.create"
    )
    completed = json.loads(raw.data or b"{}")
    assert_valid("common/message-envelope.v1.schema.json", completed)
    assert completed["actionId"].startswith(f"{resource_id}.1.create.")

    # 2. Renomear e atualizar contatos: o Executor aplica e o Observer lê o estado novo.
    renamed = display_name + " B"
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {
                "resourceVersion": updated["data"]["resourceVersion"],
                "specification": {
                    "displayName": renamed,
                    "billingContacts": ["finops@acme.com.br", "cfo@acme.com.br"],
                },
            },
        ),
    )
    await wait_for(
        jetstream, "observed", resource_id, lambda m: m["data"].get("displayName") == renamed
    )
    updated = await ready_after(jetstream, resource_id, updated["data"]["resourceVersion"])

    # 3. Remoção: o Executor remove o estado, o Observer confirma a ausência e o Manager
    # apaga o registro (`removed`).
    version = updated["data"]["resourceVersion"]
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    await asyncio.sleep(3.0)
    assert not (await last(jetstream, "updated", resource_id))["data"].get("removed")
    version = await unprotect_through_the_loop(jetstream, resource_id, version)
    unprotected = await last(jetstream, "observed", resource_id)
    assert unprotected["data"]["deletionProtection"] is False
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    removed = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"].get("removed") is True
    )
    assert removed["data"]["removed"] is True
    absent = await last(jetstream, "observed", resource_id)
    assert (absent["presence"], absent["data"]) == ("absent", {})


async def test_a_display_name_already_used_by_the_same_owner_never_reaches_the_provider(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    display_name = "Dup " + uuid.uuid4().hex[:10]
    first, _ = await create_ready(jetstream, created, display_name)

    second = str(uuid.uuid7())
    created.append(second)
    await send(
        jetstream,
        request(
            second,
            "create",
            {
                "specification": {
                    "displayName": display_name,
                    "billingCurrency": "BRL",
                    "billingContacts": ["finops@acme.com.br"],
                }
            },
        ),
    )
    await asyncio.sleep(3.0)

    with pytest.raises(Exception, match=r"no message found|not found"):
        await jetstream.get_last_msg("DESIRED", subject_of("desired", second)[1])
    assert first != second


async def test_core_account_ready_provisions_free_tier_billing_account(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    account_id = str(uuid.uuid7())
    free_tier_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bsm.account:free-tier:{account_id}"))
    created.append(free_tier_id)
    now = datetime.now(UTC).isoformat()
    desired_account = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "desired",
        "emitter": "manager",
        "module": "core",
        "resourceType": "account",
        "resourceId": account_id,
        "operation": "changed",
        "desiredGeneration": 1,
        "requestedBy": account_id,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": now,
        "publishedAt": now,
        "data": {
            "lifecycle": "present",
            "reconciliation": "active",
            "email": f"free-tier-{account_id[:8]}@example.com",
            "displayName": "Free Tier Tester",
            "deletionProtection": True,
        },
    }
    await jetstream.publish(
        f"manager.desired.core.account.{account_id}.changed",
        json.dumps(desired_account).encode(),
        headers={"Nats-Msg-Id": desired_account["messageId"]},
    )

    updated_account = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "updated",
        "emitter": "manager",
        "module": "core",
        "resourceType": "account",
        "resourceId": account_id,
        "operation": "changed",
        "correlationId": desired_account["correlationId"],
        "occurredAt": now,
        "publishedAt": now,
        "data": {
            "lifecycle": "present",
            "phase": "Ready",
            "resourceVersion": "3",
            "desiredGeneration": 1,
            "observedGeneration": 1,
        },
    }
    await jetstream.publish(
        f"manager.updated.core.account.{account_id}.changed",
        json.dumps(updated_account).encode(),
        headers={"Nats-Msg-Id": updated_account["messageId"]},
    )

    updated_bsm = await wait_for(
        jetstream, "updated", free_tier_id, lambda m: m["data"]["phase"] == "Ready"
    )
    assert updated_bsm["data"]["phase"] == "Ready"
    desired_bsm = await last(jetstream, "desired", free_tier_id)
    assert desired_bsm["data"] == {
        "lifecycle": "present",
        "reconciliation": "active",
        "displayName": "Free Tier",
        "billingCurrency": "BRL",
        "billingContacts": [f"free-tier-{account_id[:8]}@example.com"],
        "deletionProtection": True,
        "ownerAccountId": account_id,
    }
