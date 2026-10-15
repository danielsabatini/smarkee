"""Conformidade de core.user: Receiver, mensageria e SSOT pela rede."""

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from contracts import assert_valid
from nats.js import JetStreamContext

DESIRED_SUBJECT = "manager.desired.core.user.{resource_id}.changed"
REQUESTED_SUBJECT = "receiver.requested.core.user.{resource_id}.{operation}"
DIGEST = "0" * 64
MAILPIT_URL = os.environ.get("CONFORMANCE_MAILPIT_URL")


async def last_desired(
    jetstream: JetStreamContext, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            raw = await jetstream.get_last_msg(
                "DESIRED", DESIRED_SUBJECT.format(resource_id=resource_id)
            )
            return json.loads(raw.data or b"{}")
        except Exception:  # ainda não publicado: tenta de novo até o prazo
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.2)


def requested_message(resource_id: str) -> dict[str, Any]:
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "requested",
        "emitter": "receiver",
        "module": "core",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": "create",
        "requestedBy": "anonymous",
        "correlationId": str(uuid.uuid7()),
        "occurredAt": "2026-10-10T12:00:00Z",
        "publishedAt": "2026-10-10T12:00:00Z",
        "data": {
            "operationId": str(uuid.uuid7()),
            "requestDigest": DIGEST,
            "specification": {
                "givenName": "Ana",
                "familyName": "Souza",
                "email": f"conf.{uuid.uuid4().hex[:10]}@example.com",
            },
        },
    }


# ---------------------------------------------------------------------- mensageria + SSOT


async def test_requested_becomes_a_valid_desired(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    message = requested_message(resource_id)
    assert_valid("common/message-envelope.v1.schema.json", message)
    await jetstream.publish(
        REQUESTED_SUBJECT.format(resource_id=resource_id, operation="create"),
        json.dumps(message).encode(),
        headers={"Nats-Msg-Id": message["messageId"]},
    )

    desired = await last_desired(jetstream, resource_id)

    assert_valid("common/message-envelope.v1.schema.json", desired)
    assert (desired["messageType"], desired["emitter"], desired["operation"]) == (
        "desired",
        "manager",
        "changed",
    )
    # O emissor é quem decidiu (Manager); `publishedBy` é quem entregou (Publisher).
    assert desired["publishedBy"] == "core-user-publisher"
    assert desired["desiredGeneration"] == 1
    assert desired["causationId"] == message["messageId"]
    assert desired["correlationId"] == message["correlationId"]
    assert_valid("core/user/desired.v1.schema.json", desired["data"])


async def test_consumers_ignore_an_unknown_field_of_a_newer_minor(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    """Leitura tolerante (`SCHEMA.md` §15): um MINOR mais novo pode acrescentar campos."""
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    message = requested_message(resource_id)
    assert_valid("common/message-envelope.v1.schema.json", message)
    newer = {**message, "schemaVersion": "1.1", "campoDeUmaVersaoNova": "x"}
    await jetstream.publish(
        REQUESTED_SUBJECT.format(resource_id=resource_id, operation="create"),
        json.dumps(newer).encode(),
        headers={"Nats-Msg-Id": newer["messageId"]},
    )

    desired = await last_desired(jetstream, resource_id)

    assert desired["causationId"] == message["messageId"]
    assert desired["desiredGeneration"] == 1


async def test_repeated_request_does_not_publish_a_second_desired(
    jetstream: JetStreamContext, created: list[str]
) -> None:
    resource_id = str(uuid.uuid7())
    created.append(resource_id)
    first = requested_message(resource_id)
    subject = REQUESTED_SUBJECT.format(resource_id=resource_id, operation="create")
    await jetstream.publish(subject, json.dumps(first).encode())
    original = await last_desired(jetstream, resource_id)

    repeat = {**first, "messageId": str(uuid.uuid7())}  # reentrega com outro messageId
    await jetstream.publish(subject, json.dumps(repeat).encode())
    await asyncio.sleep(2.0)

    assert await last_desired(jetstream, resource_id) == original


# ---------------------------------------------------------------------- Receiver


async def test_missing_token_is_401_with_the_error_contract(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/core/users/qualquer")
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get(
        "/v1/core/users/qualquer",
        headers={"Authorization": "Bearer invalido"},
    )
    assert response.status_code == 401


async def test_registration_is_anonymous_uniform_and_reaches_the_ssot(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    email = f"conf.{uuid.uuid4().hex[:10]}@example.com"
    body = {"givenName": "Ana", "familyName": "Souza", "email": email}

    first = await api.post("/v1/core/users", json=body)
    second = await api.post("/v1/core/users", json=body)

    assert (first.status_code, second.status_code) == (202, 202)
    for response in (first, second):
        assert_valid("common/api-accepted-response.v1.schema.json", response.json())
        assert set(response.json()) == {"resourceId", "operationId"}
        created.append(response.json()["resourceId"])
    desired = await last_desired(jetstream, first.json()["resourceId"])
    assert_valid("core/user/desired.v1.schema.json", desired["data"])
    assert desired["requestedBy"] == "anonymous"


async def test_registration_rejects_a_password(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/v1/core/users",
        json={
            "givenName": "Ana",
            "familyName": "Souza",
            "email": "a@example.com",
            "password": "Segredo!123",
        },
    )
    assert response.status_code == 400
    assert "Segredo!123" not in response.text  # o valor enviado nunca é repetido


# ---------------------------------------------------------------------- loop completo


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


async def test_the_whole_loop_runs_against_zitadel_and_the_user_is_removed_at_the_end(
    api: httpx.AsyncClient, jetstream: JetStreamContext, created: list[str]
) -> None:
    """Os componentes reais (Receiver a Executor) e o Zitadel."""
    email = f"loop.{uuid.uuid4().hex[:10]}@example.com"
    body = {"givenName": "Ana", "familyName": "Souza", "email": email}

    # 1. Solicitação anônima: 202 uniforme.
    response = await api.post("/v1/core/users", json=body)
    assert response.status_code == 202
    resource_id = response.json()["resourceId"]
    created.append(resource_id)

    # 2. O loop converge sozinho (Observer e Executor reais).
    updated = await wait_for(
        jetstream,
        "UPDATED",
        f"manager.updated.core.user.{resource_id}.changed",
        lambda m: m["data"]["phase"] == "Ready",
        timeout=60.0,
    )
    assert_valid("common/updated.v1.schema.json", updated["data"])

    # 3. O Executor concluiu a criação e o Observer confirmou: usuário presente, com acesso.
    completed = await last_message(
        jetstream, "RESULT", f"executor.completed.core.user.{resource_id}.create"
    )
    assert_valid("common/message-envelope.v1.schema.json", completed)
    assert completed["actionId"].startswith(f"{resource_id}.1.create.")
    observed = await last_message(
        jetstream, "OBSERVED", f"observer.observed.core.user.{resource_id}.changed"
    )
    assert observed["presence"] == "present"
    assert_valid("core/user/observed.v1.schema.json", observed["data"])
    assert observed["data"]["platformAccess"] == "granted"
    # As roles que o Executor concedeu (as do desired) são as que o Observer leu (decisão 0025).
    desired = await last_desired(jetstream, resource_id)
    assert desired["data"]["platformRoles"]
    assert set(desired["data"]["platformRoles"]) <= set(observed["data"]["platformRoles"])
    assert observed["data"]["userState"] == "initial"  # a senha ainda não foi definida
    assert observed["data"]["emailVerified"] is False

    # 4. A pessoa recebe os e-mails do Zitadel (verificação e link para definir a senha).
    if MAILPIT_URL is not None:
        subjects = await mails_to(email)
        assert "Verificar e-mail" in subjects
        assert "Redefinir senha" in subjects

    # 5. O mesmo e-mail de novo: resposta idêntica, mas nenhum desired (Manager rejeita).
    again = await api.post("/v1/core/users", json=body)
    assert again.status_code == 202
    created.append(again.json()["resourceId"])
    await asyncio.sleep(3.0)
    with pytest.raises(Exception, match=r"no message found|not found"):
        await jetstream.get_last_msg(
            "DESIRED", DESIRED_SUBJECT.format(resource_id=again.json()["resourceId"])
        )
