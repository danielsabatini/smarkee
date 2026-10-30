"""Conformidade de core.account pela rede: gateway, API, mensageria e SSOT.

O cadastro entra anônimo pela API (decisão 0098): `202` com o `resourceId`, sem Operation. O
Controller converge a conta no Zitadel; o teste lê o `desired` e o `updated` no NATS e o `observed`
no SSOT, e valida tudo contra os JSON Schemas de `schemas/`.
"""

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from conftest import read_ssot
from contracts import assert_valid
from nats.js import JetStreamContext

DESIRED_SUBJECT = "desired.core.account.{resource_id}"
UPDATED_SUBJECT = "updated.core.account.{resource_id}"
MAILPIT_URL = os.environ.get("CONFORMANCE_MAILPIT_URL")
READY_SECONDS = 60.0


async def last_message(
    jetstream: JetStreamContext, stream: str, subject: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            raw = await jetstream.get_last_msg(stream, subject)
            return json.loads(raw.data or b"{}")
        except Exception:  # ainda não publicado: tenta de novo até o prazo
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.2)


async def last_desired(
    jetstream: JetStreamContext, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    return await last_message(
        jetstream, "DESIRED", DESIRED_SUBJECT.format(resource_id=resource_id), timeout=timeout
    )


async def wait_for(
    jetstream: JetStreamContext,
    stream: str,
    subject: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        message = await last_message(jetstream, stream, subject, timeout=timeout)
        if predicate(message):
            return message
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"{subject}: condição não atendida: {message}")
        await asyncio.sleep(0.3)


async def wait_ready(jetstream: JetStreamContext, resource_id: str) -> dict[str, Any]:
    """O `updated` em que a observação confirma a geração (decisão 0072)."""
    return await wait_for(
        jetstream,
        "UPDATED",
        UPDATED_SUBJECT.format(resource_id=resource_id),
        lambda m: (
            m["data"]["phase"] == "Ready"
            and m["data"].get("observedGeneration") == m["data"].get("desiredGeneration")
        ),
        timeout=READY_SECONDS,
    )


def registration_body(prefix: str = "test-conf") -> dict[str, str]:
    return {
        "givenName": "Ana",
        "familyName": "Souza",
        "email": f"{prefix}-{uuid.uuid4().hex[:10]}@example.com",
    }


# ---------------------------------------------------------------------- autenticação


async def test_missing_token_is_401_with_the_error_contract(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/core/accounts/qualquer")
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get(
        "/v1/core/accounts/qualquer",
        headers={"Authorization": "Bearer invalido"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------- cadastro anônimo


async def test_registration_rejects_a_password(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/v1/core/accounts",
        json={**registration_body(), "password": "Segredo!123"},
    )
    assert response.status_code == 400
    assert "Segredo!123" not in response.text  # o valor enviado nunca é repetido


async def test_registration_is_anonymous_uniform_and_reaches_the_ssot(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    body = registration_body()

    first = await api.post("/v1/core/accounts", json=body)
    second = await api.post("/v1/core/accounts", json=body)

    assert (first.status_code, second.status_code) == (202, 202)
    for response in (first, second):
        assert_valid("core/account/api-registration-response.v1.schema.json", response.json())
        assert set(response.json()) == {"resourceId"}  # sem Operation (decisão 0098)
        created.append(response.json()["resourceId"])
    assert first.json()["resourceId"] != second.json()["resourceId"]

    desired = await last_desired(jetstream, first.json()["resourceId"])
    assert_valid("common/message-envelope.v1.schema.json", desired)
    assert (desired["messageType"], desired["emitter"], desired["operation"]) == (
        "desired",
        "api",
        "changed",
    )
    assert desired["requestedBy"] == "anonymous"
    assert desired["desiredGeneration"] == 1
    assert desired["publishedBy"] == "core-account-publisher"
    assert_valid("core/account/desired.v1.schema.json", desired["data"])
    assert desired["data"]["deletionProtection"] is True
    assert desired["data"]["platformPermissions"]


async def test_registration_with_a_known_email_looks_the_same_and_publishes_nothing(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    body = registration_body()
    first = await api.post("/v1/core/accounts", json=body)
    created.append(first.json()["resourceId"])
    await last_desired(jetstream, first.json()["resourceId"])

    again = await api.post("/v1/core/accounts", json={**body, "email": body["email"].upper()})

    assert again.status_code == 202
    assert_valid("core/account/api-registration-response.v1.schema.json", again.json())
    created.append(again.json()["resourceId"])
    await asyncio.sleep(2.0)
    with pytest.raises(Exception, match=r"no message found|not found"):
        await jetstream.get_last_msg(
            "DESIRED", DESIRED_SUBJECT.format(resource_id=again.json()["resourceId"])
        )


# ---------------------------------------------------------------------- loop completo


async def mails_to(address: str, *, timeout: float = 20.0) -> list[str]:
    """Assuntos dos e-mails capturados pelo Mailpit para um destinatário."""
    assert MAILPIT_URL is not None
    deadline = asyncio.get_running_loop().time() + timeout
    subjects: list[str] = []
    async with httpx.AsyncClient(base_url=MAILPIT_URL, timeout=5.0) as mailpit:
        while asyncio.get_running_loop().time() < deadline:
            found = (await mailpit.get("/api/v1/search", params={"query": f"to:{address}"})).json()
            subjects = [message["Subject"] for message in found.get("messages", [])]
            if len(subjects) >= 2:
                break
            await asyncio.sleep(0.5)
    return subjects


async def test_the_whole_loop_converges_the_account_at_the_identity_provider(
    api: httpx.AsyncClient,
    jetstream: JetStreamContext,
    headers: dict[str, str],
    created: list[str],
) -> None:
    """API, Publisher, Controller e o Zitadel reais."""
    body = registration_body("test-loop")

    response = await api.post("/v1/core/accounts", json=body)
    assert response.status_code == 202
    resource_id = response.json()["resourceId"]
    created.append(resource_id)

    updated = await wait_ready(jetstream, resource_id)
    assert_valid("common/updated.v1.schema.json", updated["data"])

    # O Controller grava o observado no SSOT: usuário presente, com acesso e protegido.
    ssot = await read_ssot(resource_id)
    if ssot is not None:
        assert ssot["presence"] == "present"
        assert_valid("core/account/observed.v1.schema.json", ssot["data"])
        assert ssot["data"]["platformAccess"] == "granted"
        desired = await last_desired(jetstream, resource_id)
        assert set(desired["data"]["platformPermissions"]) <= set(
            ssot["data"]["platformPermissions"]
        )
        assert ssot["data"]["accountState"] == "initial"  # a senha ainda não foi definida
        assert ssot["data"]["deletionProtection"] is True  # metadado no Zitadel (decisão 0074)
        assert ssot["data"]["emailVerified"] is False

    # O operador lê a conta pela API.
    read = await api.get(f"/v1/core/accounts/{resource_id}", headers=headers)
    assert read.status_code == 200
    assert_valid("core/account/resource.v1.schema.json", read.json())
    assert read.json()["phase"] == "Ready"

    # A pessoa recebe o e-mail do Zitadel: o de verificação, que também define a senha.
    if MAILPIT_URL is not None:
        subjects = await mails_to(body["email"])
        assert "Verificar e-mail" in subjects
        assert "Redefinir senha" not in subjects  # um e-mail só: o de verificação já define a senha


async def test_the_operator_cannot_delete_another_account_but_can_unprotect_it(
    api: httpx.AsyncClient,
    jetstream: JetStreamContext,
    headers: dict[str, str],
    created: list[str],
) -> None:
    response = await api.post("/v1/core/accounts", json=registration_body("test-loop"))
    resource_id = response.json()["resourceId"]
    created.append(resource_id)
    await wait_ready(jetstream, resource_id)
    read = await api.get(f"/v1/core/accounts/{resource_id}", headers=headers)
    version = read.json()["resourceVersion"]

    # O operador não é o dono: a exclusão não consegue verificar os recursos atrelados.
    refused = await api.delete(
        f"/v1/core/accounts/{resource_id}", params={"resourceVersion": version}, headers=headers
    )
    assert refused.status_code == 409
    assert_valid("common/api-error.v1.schema.json", refused.json())
    assert refused.json()["errorCode"] in {"DeletionProtected", "ResourcesNotVerifiable"}

    # Tirar a proteção é permitido ao operador: 200 com o recurso na nova geração.
    patched = await api.patch(
        f"/v1/core/accounts/{resource_id}",
        json={"resourceVersion": version, "deletionProtection": False},
        headers=headers,
    )
    assert patched.status_code == 200
    assert_valid("core/account/resource.v1.schema.json", patched.json())
    assert patched.json()["desired"]["deletionProtection"] is False
