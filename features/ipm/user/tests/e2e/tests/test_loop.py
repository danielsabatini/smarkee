"""Loop completo de ipm.user (API ao Controller), com o Zitadel de dev.

Os pedidos entram pela API HTTP (decisão 0098), com o token de um operador
(`CONFORMANCE_ACCESS_TOKEN`), numa Organization preparada pelo operador
(`CONFORMANCE_ORGANIZATION_ID`). Cada usuário é removido pelo próprio loop ao final
(fixture `created`).
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from conftest import current_row, read_ssot
from contracts import assert_valid
from nats.js import JetStreamContext

READY_SECONDS = 60.0


def subject_of(kind: str, resource_id: str) -> tuple[str, str]:
    """Stream e Subject da última mensagem de cada tipo do recurso."""
    return {
        "desired": ("DESIRED", f"manager.desired.ipm.user.{resource_id}.changed"),
        "updated": ("UPDATED", f"manager.updated.ipm.user.{resource_id}.changed"),
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


async def confirmed(
    jetstream: JetStreamContext, resource_id: str, generation: int
) -> dict[str, Any]:
    """O `updated` em que a observação confirma a geração (decisão 0072)."""
    return await wait_for(
        jetstream,
        "updated",
        resource_id,
        lambda m: (
            m["data"]["phase"] == "Ready"
            and m["data"].get("desiredGeneration") == generation
            and m["data"].get("observedGeneration") == generation
        ),
    )


async def settled_version(resource_id: str) -> str:
    """A `resourceVersion` atual, depois que ela para de mudar.

    Depois de cada `updated`, o Controller ainda grava a observação seguinte (que
    sobe a versão): um cliente real lê a versão atual antes de alterar, e é isso que o teste imita.
    Usar a versão de um `updated` já superado faz a API recusar o pedido (`409 Conflict`).
    """
    current = await current_row(resource_id)
    assert current is not None
    while True:
        await asyncio.sleep(1.5)
        latest = await current_row(resource_id)
        assert latest is not None
        if latest["resource_version"] == current["resource_version"]:
            return str(latest["resource_version"])
        current = latest


COLLECTION = "/v1/ipm/users"


async def post(
    api: httpx.AsyncClient, headers: dict[str, str], specification: dict[str, Any]
) -> dict[str, Any]:
    """`POST` da API: devolve o recurso (`201`)."""
    response = await api.post(COLLECTION, json=specification, headers=headers)
    assert response.status_code == 201, response.text
    resource = response.json()
    assert_valid("ipm/user/resource.v1.schema.json", resource)
    return resource


async def patch(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    resource_id: str,
    version: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """`PATCH` da API: devolve o recurso (`200`)."""
    response = await api.patch(
        f"{COLLECTION}/{resource_id}",
        json={"resourceVersion": version, **changes},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def specification(organization_id: str, roles: list[str]) -> dict[str, Any]:
    return {
        "organizationId": organization_id,
        "givenName": "Loop",
        "familyName": "User",
        "email": f"loop-{uuid.uuid4().hex[:10]}@example.com",
        "roles": roles,
        "deletionProtection": False,
    }


async def test_the_whole_loop_creates_changes_permissions_protects_and_removes_the_user(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    jetstream: JetStreamContext,
    created: list[str],
    organization_id: str,
) -> None:
    # 1. Criação: o usuário nasce na Organization, sem senha. As `roles` são expandidas pelo
    # Controller em permissões efetivas (decisões 0085 e 0097); o `desired` guarda só a intenção.
    resource = await post(api, headers, specification(organization_id, ["ipm.userViewer"]))
    resource_id = str(resource["resourceId"])
    created.append(resource_id)
    assert (resource["phase"], resource["desiredGeneration"]) == ("Pending", 1)
    assert "observedGeneration" not in resource  # ainda não observado

    updated = await confirmed(jetstream, resource_id, 1)
    assert_valid("common/updated.v1.schema.json", updated["data"])
    desired = await last(jetstream, "desired", resource_id)
    assert_valid("ipm/user/desired.v1.schema.json", desired["data"])
    observed = await observed_where(resource_id, lambda m: m.get("presence") == "present")
    assert_valid("ipm/user/observed.v1.schema.json", observed["data"])
    assert desired["data"]["roles"] == ["ipm.userViewer"]
    assert "permissions" not in desired["data"]
    assert observed["data"]["permissions"] == ["ipm.user.get", "ipm.user.list"]
    assert observed["data"]["effectivePermissions"] == ["ipm.user.get", "ipm.user.list"]
    assert observed["data"]["deletionProtection"] is False  # nasce desprotegido (decisão 0077)
    assert observed["data"]["userState"] == "initial"  # ativa pelo e-mail, sem senha
    assert "email" not in observed["data"]  # o observado não traz dado pessoal

    # 2. Roles: o Controller recalcula as efetivas e deixa no Zitadel exatamente essas.
    version = await settled_version(resource_id)
    permissions = [
        "ipm.user.bind",
        "ipm.user.create",
        "ipm.user.delete",
        "ipm.user.get",
        "ipm.user.list",
        "ipm.user.update",
    ]
    changed = await patch(api, headers, resource_id, version, {"roles": ["ipm.userAdmin"]})
    assert changed["desiredGeneration"] == 2
    await confirmed(jetstream, resource_id, 2)
    observed = await observed_where(
        resource_id,
        lambda m: (
            m["data"].get("permissions") == permissions
            and m["data"].get("effectivePermissions") == permissions
        ),
    )

    # 3. Proteção: gravada como metadado no usuário e observada de volta (decisão 0074).
    await patch(
        api, headers, resource_id, await settled_version(resource_id), {"deletionProtection": True}
    )
    await confirmed(jetstream, resource_id, 3)
    await observed_where(resource_id, lambda m: m["data"].get("deletionProtection") is True)

    # 4. A convergência também se lê pela API: `observedGeneration` alcança a geração desejada.
    read = await api.get(f"{COLLECTION}/{resource_id}", headers=headers)
    assert read.status_code == 200
    assert read.json()["observedGeneration"] == read.json()["desiredGeneration"] == 3
    # 5. A remoção (fixture `created`) tira a proteção e remove o usuário pelo loop.


async def test_a_role_permission_outside_the_grant_is_not_granted(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    jetstream: JetStreamContext,
    created: list[str],
    organization_id: str,
) -> None:
    """O Project Grant é o teto (decisão 0077): o Controller só expande permissões delegáveis.

    `ipm.organizationAdmin` traz `ipm.organization.create` e `ipm.organization.delete`, que existem
    no `roles-ipm` mas não são delegáveis à Organization (decisão 0092); ficam de fora das
    permissões efetivas e, portanto, do Zitadel. A recusa do provedor (`Rejected`) deixou de ser
    alcançável por esse caminho.
    """
    resource = await post(api, headers, specification(organization_id, ["ipm.organizationAdmin"]))
    resource_id = str(resource["resourceId"])
    created.append(resource_id)
    await confirmed(jetstream, resource_id, 1)
    desired = await last(jetstream, "desired", resource_id)
    assert_valid("ipm/user/desired.v1.schema.json", desired["data"])
    granted = ["ipm.organization.get", "ipm.organization.list", "ipm.organization.update"]
    assert "permissions" not in desired["data"]
    observed = await observed_where(
        resource_id, lambda m: m["data"].get("effectivePermissions") == granted
    )
    assert observed["data"]["permissions"] == granted
