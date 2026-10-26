"""Loop completo de ipm.serviceaccount (Receiver ao Observer), com o Zitadel de dev.

Os pedidos entram direto no NATS, como o Receiver os publicaria, numa Organization preparada pelo
operador (`CONFORMANCE_ORGANIZATION_ID`). Cada service account é removida pelo próprio loop ao final
(fixture `created`).
"""

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from conftest import current_row, request, send
from contracts import assert_valid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from nats.js import JetStreamContext

READY_SECONDS = 60.0


def subject_of(kind: str, resource_id: str) -> tuple[str, str]:
    """Stream e Subject da última mensagem de cada tipo do recurso."""
    return {
        "desired": ("DESIRED", f"manager.desired.ipm.serviceaccount.{resource_id}.changed"),
        "observed": ("OBSERVED", f"observer.observed.ipm.serviceaccount.{resource_id}.changed"),
        "updated": ("UPDATED", f"manager.updated.ipm.serviceaccount.{resource_id}.changed"),
        "failed": ("RESULT", f"executor.failed.ipm.serviceaccount.{resource_id}.create"),
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


def desired_key() -> dict[str, str]:
    """Uma chave pública nova, como o Receiver a entregaria (com o fingerprint do DER SPKI)."""
    public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    pem = public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    der = public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    expires = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "publicKey": pem,
        "expiresAt": expires,
        "fingerprint": hashlib.sha256(der).hexdigest(),
    }


def specification(
    organization_id: str, permissions: list[str], keys: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "organizationId": organization_id,
        "name": f"loop-{uuid.uuid4().hex[:10]}",
        "permissions": permissions,
        "deletionProtection": False,
        "keys": keys if keys is not None else [desired_key()],
    }


async def test_the_whole_loop_creates_changes_permissions_keys_protects_and_removes(
    jetstream: JetStreamContext, created: list[str], organization_id: str
) -> None:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    first_key = desired_key()

    # 1. Criação: a máquina nasce na Organization com o token JWT, a chave pública e as permissões.
    await send(
        jetstream,
        request(
            resource_id,
            "create",
            {
                "specification": specification(
                    organization_id, ["ipm.serviceaccount.get"], [first_key]
                )
            },
        ),
    )
    updated = await confirmed(jetstream, resource_id, 1)
    assert_valid("common/updated.v1.schema.json", updated["data"])
    desired = await last(jetstream, "desired", resource_id)
    assert_valid("ipm/serviceaccount/desired.v1.schema.json", desired["data"])
    observed = await wait_for(
        jetstream,
        "observed",
        resource_id,
        lambda m: m.get("presence") == "present" and bool(m["data"].get("keys")),
    )
    assert_valid("ipm/serviceaccount/observed.v1.schema.json", observed["data"])
    assert observed["data"]["permissions"] == ["ipm.serviceaccount.get"]
    assert observed["data"]["deletionProtection"] is False
    assert observed["data"]["accessTokenType"] == "jwt"
    assert [(k["fingerprint"], k["status"]) for k in observed["data"]["keys"]] == [
        (first_key["fingerprint"], "active")
    ]
    assert "publicKey" not in json.dumps(observed["data"])  # o Observer só devolve identificadores

    # 2. Permissões: o Executor deixa no Zitadel exatamente as do `desired`.
    version = await settled_version(resource_id)
    permissions = ["ipm.serviceaccount.get", "ipm.serviceaccount.list"]
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {"resourceVersion": version, "specification": {"permissions": permissions}},
        ),
    )
    await confirmed(jetstream, resource_id, 2)
    await wait_for(
        jetstream, "observed", resource_id, lambda m: m["data"].get("permissions") == permissions
    )

    # 3. Rotação: entra a segunda chave e a primeira sai; o mapa de fingerprints acompanha.
    second_key = desired_key()
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {
                "resourceVersion": await settled_version(resource_id),
                "specification": {"keys": [first_key, second_key]},
            },
        ),
    )
    await confirmed(jetstream, resource_id, 3)
    both = {first_key["fingerprint"], second_key["fingerprint"]}
    await wait_for(
        jetstream,
        "observed",
        resource_id,
        lambda m: (
            {k["fingerprint"] for k in m["data"].get("keys", [])} == both
            and all(k["status"] == "active" for k in m["data"]["keys"])
        ),
    )
    await send(
        jetstream,
        request(
            resource_id,
            "update",
            {
                "resourceVersion": await settled_version(resource_id),
                "specification": {"keys": [second_key]},
            },
        ),
    )
    await confirmed(jetstream, resource_id, 4)
    await wait_for(
        jetstream,
        "observed",
        resource_id,
        lambda m: (
            [k["fingerprint"] for k in m["data"].get("keys", [])] == [second_key["fingerprint"]]
        ),
    )

    # 4. Proteção: gravada como metadado na máquina e observada de volta (decisão 0074).
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
    await confirmed(jetstream, resource_id, 5)
    await wait_for(
        jetstream, "observed", resource_id, lambda m: m["data"].get("deletionProtection") is True
    )
    # 5. A remoção (fixture `created`) tira a proteção e remove a máquina pelo loop.


async def test_a_permission_outside_the_grant_is_refused_by_the_provider(
    jetstream: JetStreamContext, created: list[str], organization_id: str
) -> None:
    """O Project Grant é o teto: o Zitadel recusa permissão fora do Grant (decisão 0077).

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
