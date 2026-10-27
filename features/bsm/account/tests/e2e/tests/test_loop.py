"""Loop de bsm.account (API até o Publisher), com os componentes reais.

A Billing Account é dado do SSOT (decisões 0082 e 0098, S6.1): os pedidos entram pela API HTTP
com o token de um operador (`CONFORMANCE_ACCESS_TOKEN`); o recurso nasce `Ready` e o `desired` sai
pelo outbox. Cada Billing Account é removida pela própria API ao final (fixture `created`).
"""

import asyncio
import json
import uuid
from typing import Any

import httpx
from conftest import current_row
from contracts import assert_valid
from nats.js import JetStreamContext

COLLECTION = "/v1/bsm/accounts"


async def last_desired(
    jetstream: JetStreamContext, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    """Última mensagem `desired` do recurso (o Publisher a entrega a partir do outbox)."""
    subject = f"manager.desired.bsm.account.{resource_id}.changed"
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return json.loads((await jetstream.get_last_msg("DESIRED", subject)).data or b"{}")
        except Exception:
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.3)


async def desired_where(
    jetstream: JetStreamContext, resource_id: str, generation: int
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 30.0
    while True:
        message = await last_desired(jetstream, resource_id)
        if message["desiredGeneration"] == generation:
            return message
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"desired: geração {generation} não publicada: {message}")
        await asyncio.sleep(0.3)


def specification(name: str | None = None) -> dict[str, Any]:
    return {
        "displayName": name or f"Test Account {uuid.uuid4().hex[:6]}",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.example"],
    }


async def test_the_whole_flow_creates_updates_protects_and_removes_the_account(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    jetstream: JetStreamContext,
    created: list[str],
) -> None:
    body = specification()
    assert_valid("bsm/account/api-create-request.v1.schema.json", body)

    # 1. Criação: nasce `Ready` e convergida, e o `desired` sai pelo outbox.
    response = await api.post(COLLECTION, json=body, headers=headers)
    assert response.status_code == 201, response.text
    resource = response.json()
    resource_id = str(resource["resourceId"])
    created.append(resource_id)
    assert_valid("bsm/account/resource.v1.schema.json", resource)
    assert (resource["phase"], resource["desiredGeneration"]) == ("Ready", 1)
    assert resource["observedGeneration"] == 1
    assert resource["deletionProtection"] is True
    desired = await desired_where(jetstream, resource_id, 1)
    assert_valid("common/message-envelope.v1.schema.json", desired)
    assert desired["emitter"] == "api"
    assert_valid("bsm/account/desired.v1.schema.json", desired["data"])
    assert desired["data"]["displayName"] == body["displayName"]

    # 2. Atualização: novo nome e contato; a geração sobe e o `desired` acompanha.
    new_name = f"Updated Account {uuid.uuid4().hex[:6]}"
    patched = await api.patch(
        f"{COLLECTION}/{resource_id}",
        json={
            "resourceVersion": resource["resourceVersion"],
            "displayName": new_name,
            "billingContacts": ["new@acme.example"],
        },
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert (patched.json()["desiredGeneration"], patched.json()["phase"]) == (2, "Ready")
    desired = await desired_where(jetstream, resource_id, 2)
    assert desired["data"]["displayName"] == new_name

    # 3. Proteção contra exclusão: a remoção é recusada enquanto `deletionProtection` é true.
    version = patched.json()["resourceVersion"]
    refused = await api.delete(
        f"{COLLECTION}/{resource_id}", params={"resourceVersion": version}, headers=headers
    )
    assert refused.status_code == 409, refused.text
    assert (await current_row(resource_id)) is not None

    # 4. Desproteger e remover: a linha sai do SSOT e o tombstone é publicado.
    unprotected = await api.patch(
        f"{COLLECTION}/{resource_id}",
        json={"resourceVersion": version, "deletionProtection": False},
        headers=headers,
    )
    assert unprotected.status_code == 200, unprotected.text
    deleted = await api.delete(
        f"{COLLECTION}/{resource_id}",
        params={"resourceVersion": unprotected.json()["resourceVersion"]},
        headers=headers,
    )
    assert deleted.status_code == 202, deleted.text
    assert deleted.json()["phase"] == "Deleting"
    assert await current_row(resource_id) is None
    tombstone = await desired_where(jetstream, resource_id, 4)
    assert tombstone["data"]["lifecycle"] == "absent"
    assert (await api.get(f"{COLLECTION}/{resource_id}", headers=headers)).status_code == 404
