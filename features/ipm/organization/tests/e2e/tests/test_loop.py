"""Loop completo de ipm.organization (Receiver até Controller), com componentes reais e o Zitadel.

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
from conftest import operation_statuses, read_ssot, unprotect_through_the_loop
from contracts import SCHEMAS_ROOT, assert_valid
from nats.js import JetStreamContext

DIGEST = "0" * 64
READY_SECONDS = 60.0


def subject_of(kind: str, resource_id: str) -> tuple[str, str]:
    """Stream e Subject da última mensagem de cada tipo do recurso."""
    return {
        "desired": ("DESIRED", f"manager.desired.ipm.organization.{resource_id}.changed"),
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


async def observed_where(
    resource_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = READY_SECONDS,
) -> dict[str, Any]:
    """Espera o estado observado do SSOT (gravado pelo Controller) atender à condição."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        observed = await read_ssot(resource_id)
        if observed is not None and predicate(observed):
            return observed
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"observed: condição não atendida: {observed}")
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


def grant_catalog() -> list[str]:
    """O catálogo `grantablePermission` do contrato (decisão 0081), em ordem alfabética."""
    path = SCHEMAS_ROOT / "ipm" / "definitions.v1.schema.json"
    return sorted(json.loads(path.read_text("utf-8"))["$defs"]["grantablePermission"]["enum"])


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
    observed = await observed_where(resource_id, lambda m: m["presence"] == "present")
    assert observed["presence"] == "present"
    assert_valid("ipm/organization/observed.v1.schema.json", observed["data"])
    user_access = observed["data"].pop("userAccess")
    assert observed["data"] == {
        "name": name,
        "platformAccess": "granted",
        "organizationState": "active",
        "deletionProtection": True,  # metadado no Zitadel (decisão 0074)
    }
    # Pronta para usuários (decisão 0081) e para service accounts (decisão 0094): o Grant com o
    # catálogo do contrato e as permissões das contas do ipm/user e do ipm/serviceaccount (as
    # contas de cada uma), criadas pelo loop, sem o operador.
    assert user_access["grantPermissions"] == grant_catalog()
    assert sorted(sorted(item["permissions"]) for item in user_access["administrators"]) == [
        ["ORG_OWNER_VIEWER"],
        ["ORG_OWNER_VIEWER"],
        ["ORG_OWNER_VIEWER", "ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"],
        ["ORG_OWNER_VIEWER", "ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"],
        ["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"],
        ["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"],
    ]
    assert await operation_statuses(resource_id) == ["completed"]

    # 2. Renomear: o Controller renomeia a organização e grava o nome novo no observado.
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
    await observed_where(resource_id, lambda m: m["data"].get("name") == renamed)
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
        await observed_where(
            resource_id,
            lambda m, state=state: m["data"].get("organizationState") == state,
        )
        updated = await ready_after(jetstream, resource_id, updated["data"]["resourceVersion"])

    # 4. Remoção: o Controller remove a organização, confirma a ausência e apaga o registro
    # (`removed`).
    # Nasce protegida (decisão 0043): o `delete` é rejeitado e nada muda no provedor.
    version = updated["data"]["resourceVersion"]
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    await asyncio.sleep(3.0)
    assert not (await last(jetstream, "updated", resource_id))["data"].get("removed")
    version = await unprotect_through_the_loop(jetstream, resource_id, version)
    # Desproteger percorre o loop: o Controller grava o metadado e o lê de volta (decisão 0074).
    unprotected = await observed_where(
        resource_id, lambda m: m["data"].get("deletionProtection") is False
    )
    assert unprotected["data"]["deletionProtection"] is False
    await send(jetstream, request(resource_id, "delete", {"resourceVersion": version}))
    removed = await wait_for(
        jetstream, "updated", resource_id, lambda m: m["data"].get("removed") is True
    )
    assert removed["data"]["removed"] is True
    assert await read_ssot(resource_id) is None  # o registro saiu do SSOT


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
