"""Loop completo de ipm.user (Receiver até Observer), com os componentes reais e o Zitadel de dev.

Os pedidos entram direto no NATS, como o Receiver os publicaria, numa Organization preparada pelo
operador (`CONFORMANCE_ORGANIZATION_ID`). Cada usuário é removido pelo próprio loop ao final
(fixture `created`).
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from typing import Any

from conftest import current_row, request, send
from contracts import assert_valid
from nats.js import JetStreamContext

READY_SECONDS = 60.0


def subject_of(kind: str, resource_id: str) -> tuple[str, str]:
    """Stream e Subject da última mensagem de cada tipo do recurso."""
    return {
        "desired": ("DESIRED", f"manager.desired.ipm.user.{resource_id}.changed"),
        "observed": ("OBSERVED", f"observer.observed.ipm.user.{resource_id}.changed"),
        "updated": ("UPDATED", f"manager.updated.ipm.user.{resource_id}.changed"),
        "failed": ("RESULT", f"executor.failed.ipm.user.{resource_id}.create"),
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

    Depois de cada `updated`, o Manager ainda grava a observação e o resultado seguintes (cada um
    sobe a versão): um cliente real lê a versão atual antes de alterar, e é isso que o teste imita.
    Usar a versão de um `updated` já superado faz o Manager recusar o pedido (`conflict`).
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


def specification(organization_id: str, roles: list[str]) -> dict[str, Any]:
    return {
        "organizationId": organization_id,
        "givenName": "Loop",
        "familyName": "User",
        "email": f"loop-{uuid.uuid4().hex[:10]}@example.com",
        "roles": roles,
        "deletionProtection": False,
    }


async def test_the_whole_loop_creates_changes_roles_protects_and_removes_the_user(
    jetstream: JetStreamContext, created: list[str], organization_id: str
) -> None:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)

    # 1. Criação: o usuário nasce na Organization, sem senha, com as roles do Grant.
    await send(
        jetstream,
        request(
            resource_id,
            "create",
            {"specification": specification(organization_id, ["ipm.user.get"])},
        ),
    )
    updated = await confirmed(jetstream, resource_id, 1)
    assert_valid("common/updated.v1.schema.json", updated["data"])
    desired = await last(jetstream, "desired", resource_id)
    assert_valid("ipm/user/desired.v1.schema.json", desired["data"])
    observed = await wait_for(
        jetstream, "observed", resource_id, lambda m: m.get("presence") == "present"
    )
    assert_valid("ipm/user/observed.v1.schema.json", observed["data"])
    assert observed["data"]["roles"] == ["ipm.user.get"]
    assert observed["data"]["deletionProtection"] is False  # nasce desprotegido (decisão 0077)
    assert observed["data"]["userState"] == "initial"  # ativa pelo e-mail, sem senha
    assert "email" not in observed["data"]  # o Observer não devolve dado pessoal

    # 2. Roles: o Executor deixa no Zitadel exatamente as do `desired`.
    version = await settled_version(resource_id)
    roles = ["ipm.user.get", "ipm.user.list"]
    await send(
        jetstream,
        request(
            resource_id, "update", {"resourceVersion": version, "specification": {"roles": roles}}
        ),
    )
    await confirmed(jetstream, resource_id, 2)
    observed = await wait_for(
        jetstream, "observed", resource_id, lambda m: m["data"].get("roles") == roles
    )

    # 3. Proteção: gravada como metadado no usuário e observada de volta (decisão 0074).
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {
                "resourceVersion": await settled_version(resource_id),
                "specification": {"deletionProtection": True},
            },
        ),
    )
    await confirmed(jetstream, resource_id, 3)
    await wait_for(
        jetstream, "observed", resource_id, lambda m: m["data"].get("deletionProtection") is True
    )
    # 4. A remoção (fixture `created`) tira a proteção e remove o usuário pelo loop.


async def test_a_role_outside_the_grant_is_refused_by_the_provider(
    jetstream: JetStreamContext, created: list[str], organization_id: str
) -> None:
    """O Project Grant é o teto: o Zitadel recusa a role que o operador não liberou (decisão 0077).

    `ipm.organization.delete` existe no `roles-ipm`, mas não está no Grant da Organization.
    """
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    await send(
        jetstream,
        request(
            resource_id,
            "create",
            {"specification": specification(organization_id, ["ipm.organization.delete"])},
        ),
    )
    failed = await last(jetstream, "failed", resource_id, timeout=READY_SECONDS)
    assert_valid("common/failed.v1.schema.json", failed["data"])
    assert (failed["data"]["reason"], failed["data"]["retryable"]) == ("Rejected", False)
