"""Loop de ipm.permission (API até o Controller), com os componentes reais e o Zitadel de dev.

Os pedidos entram pela API HTTP com o token de um operador (`CONFORMANCE_ACCESS_TOKEN`, que tem
`ipm.permission.admin`): o recurso nasce `Pending`, o Publisher entrega o `desired` e o Controller
cria, atualiza e remove a role no projeto `roles-<módulo>`. Cada Permission é removida pela
própria API ao final (fixture `created`).
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from contracts import assert_valid
from nats.js import JetStreamContext

COLLECTION = "/v1/ipm/permissions"
READY_SECONDS = 60.0


async def last_desired(
    jetstream: JetStreamContext, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    """Última mensagem `desired` do recurso (o Publisher a entrega a partir do outbox)."""
    subject = f"desired.ipm.permission.{resource_id}"
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return json.loads((await jetstream.get_last_msg("DESIRED", subject)).data or b"{}")
        except Exception:  # ainda não publicado: tenta de novo até o prazo
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.3)


async def resource_where(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    resource_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = READY_SECONDS,
) -> dict[str, Any]:
    """Espera o recurso lido pela API atender à condição (o Controller o atualiza no SSOT)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        response = await api.get(f"{COLLECTION}/{resource_id}", headers=headers)
        resource: dict[str, Any] = response.json()
        if response.status_code == 200 and predicate(resource):
            return resource
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"resource: condição não atendida: {resource}")
        await asyncio.sleep(0.5)


def converged(resource: dict[str, Any]) -> bool:
    return (
        resource.get("phase") == "Ready"
        and resource.get("observedGeneration", 0) >= resource["desiredGeneration"]
    )


def new_name() -> str:
    return f"bsm.e2e.p{uuid.uuid4().hex[:7]}"


async def create_ready(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    created: list[str],
    name: str,
    description: str = "Loop test permission",
) -> dict[str, Any]:
    response = await api.post(
        COLLECTION,
        json={"name": name, "description": description, "grantable": True},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    resource_id = str(response.json()["resourceId"])
    created.append(resource_id)
    return await resource_where(api, headers, resource_id, converged)


async def test_the_whole_loop_creates_updates_protects_and_removes_the_permission(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    jetstream: JetStreamContext,
    created: list[str],
) -> None:
    name = new_name()
    body = {"name": name, "description": "Permissao inicial", "grantable": True}
    assert_valid("ipm/permission/api-create-request.v1.schema.json", body)

    # 1. Criação: nasce `Pending`, o `desired` sai pelo outbox e o Controller cria a role.
    response = await api.post(COLLECTION, json=body, headers=headers)
    assert response.status_code == 201, response.text
    resource_id = str(response.json()["resourceId"])
    created.append(resource_id)
    assert_valid("ipm/permission/resource.v1.schema.json", response.json())
    assert response.json()["phase"] == "Pending"
    desired = await last_desired(jetstream, resource_id)
    assert_valid("common/message-envelope.v1.schema.json", desired)
    assert desired["emitter"] == "api"
    assert_valid("ipm/permission/desired.v1.schema.json", desired["data"])
    resource = await resource_where(api, headers, resource_id, converged)
    assert_valid("ipm/permission/resource.v1.schema.json", resource)
    # A view traz `presence` e `observedAt` junto do `data`; o schema vale só para o `data`.
    observed = dict(resource["observed"])
    assert observed.pop("presence") == "present"
    assert "observedAt" in observed
    observed.pop("observedAt")
    assert_valid("ipm/permission/observed.v1.schema.json", observed)
    assert observed == {"name": name, "description": "Permissao inicial", "group": "bsm"}

    # 2. Atualização: nova descrição; a geração sobe e o Controller atualiza a role.
    patched = await api.patch(
        f"{COLLECTION}/{resource_id}",
        json={"resourceVersion": resource["resourceVersion"], "description": "Permissao nova"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["desiredGeneration"] == 2
    resource = await resource_where(
        api,
        headers,
        resource_id,
        lambda r: converged(r) and r["observed"]["description"] == "Permissao nova",
    )

    # 3. Proteção contra exclusão: a remoção é recusada enquanto `deletionProtection` é true.
    version = resource["resourceVersion"]
    refused = await api.delete(
        f"{COLLECTION}/{resource_id}", params={"resourceVersion": version}, headers=headers
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["errorCode"] == "DeletionProtected"

    # 4. Desproteger e remover: o Controller remove a role e apaga o registro.
    unprotected = await api.patch(
        f"{COLLECTION}/{resource_id}",
        json={"resourceVersion": version, "deletionProtection": False},
        headers=headers,
    )
    assert unprotected.status_code == 200, unprotected.text
    resource = await resource_where(api, headers, resource_id, converged)
    deleted = await api.delete(
        f"{COLLECTION}/{resource_id}",
        params={"resourceVersion": resource["resourceVersion"]},
        headers=headers,
    )
    assert deleted.status_code == 202, deleted.text
    assert deleted.json()["phase"] == "Deleting"
    deadline = asyncio.get_running_loop().time() + READY_SECONDS
    while (await api.get(f"{COLLECTION}/{resource_id}", headers=headers)).status_code != 404:
        assert asyncio.get_running_loop().time() < deadline, "o registro não foi removido"
        await asyncio.sleep(0.5)
    tombstone = await last_desired(jetstream, resource_id)
    assert tombstone["data"]["lifecycle"] == "absent"


async def test_a_name_already_used_is_refused_with_conflict(
    api: httpx.AsyncClient, headers: dict[str, str], created: list[str]
) -> None:
    name = new_name()
    first = await api.post(
        COLLECTION,
        json={"name": name, "description": "Permissao unica", "grantable": True},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    created.append(first.json()["resourceId"])

    second = await api.post(
        COLLECTION,
        json={"name": name, "description": "Permissao duplicada", "grantable": True},
        headers=headers,
    )

    assert second.status_code == 409, second.text
    assert_valid("common/api-error.v1.schema.json", second.json())
    assert second.json()["errorCode"] == "NameInUse"


async def test_a_description_equal_to_the_name_is_refused(
    api: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    name = new_name()
    response = await api.post(
        COLLECTION, json={"name": name, "description": name, "grantable": True}, headers=headers
    )
    assert response.status_code == 400, response.text
    assert response.json()["field"] == "description"
