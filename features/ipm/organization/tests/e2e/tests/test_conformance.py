"""Conformidade de ipm.organization: Receiver, mensageria e SSOT pela rede."""

import asyncio
import json
import uuid
from typing import Any

import httpx
from contracts import assert_valid
from nats.js import JetStreamContext

DESIRED_SUBJECT = "desired.ipm.organization.{resource_id}"
REQUESTED_SUBJECT = "receiver.requested.ipm.organization.{resource_id}.{operation}"
DIGEST = "0" * 64


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
        "module": "ipm",
        "resourceType": "organization",
        "resourceId": resource_id,
        "operation": "create",
        "requestedBy": "conformance-user",
        "correlationId": str(uuid.uuid7()),
        "occurredAt": "2026-10-10T12:00:00Z",
        "publishedAt": "2026-10-10T12:00:00Z",
        "data": {
            "operationId": str(uuid.uuid7()),
            "requestDigest": DIGEST,
            "specification": {"name": "conf-" + uuid.uuid4().hex[:10], "platformAccess": "granted"},
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
    assert desired["desiredGeneration"] == 1
    assert desired["causationId"] == message["messageId"]
    assert desired["correlationId"] == message["correlationId"]
    assert_valid("ipm/organization/desired.v1.schema.json", desired["data"])


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
    response = await api.get("/v1/ipm/organizations")
    assert response.status_code == 401
    assert_valid("common/api-error.v1.schema.json", response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_invalid_token_is_401(api: httpx.AsyncClient) -> None:
    response = await api.get(
        "/v1/ipm/organizations",
        headers={"Authorization": "Bearer invalido"},
    )
    assert response.status_code == 401


async def test_create_is_accepted_and_the_operation_is_readable(
    api: httpx.AsyncClient,
    authorization: dict[str, str],
    jetstream: JetStreamContext,
    created: list[str],
) -> None:
    name = "conf-" + uuid.uuid4().hex[:10]
    response = await api.post("/v1/ipm/organizations", json={"name": name}, headers=authorization)
    assert response.status_code == 202, response.text
    body = response.json()
    assert_valid("common/api-accepted-response.v1.schema.json", body)
    created.append(body["resourceId"])

    operation = await api.get(
        f"/v1/ipm/organizations/{body['resourceId']}/operations/{body['operationId']}",
        headers=authorization,
    )
    assert operation.status_code == 200
    assert_valid("common/operation.v1.schema.json", operation.json())

    desired = await last_desired(jetstream, body["resourceId"])
    assert desired["data"]["name"] == name
    assert "ownerAccountId" in desired["data"]

    resource = await api.get(f"/v1/ipm/organizations/{body['resourceId']}", headers=authorization)
    assert resource.status_code == 200
    assert_valid("ipm/organization/resource.v1.schema.json", resource.json())
    assert "ownerAccountId" not in resource.text


async def test_unknown_body_field_is_400(
    api: httpx.AsyncClient, authorization: dict[str, str]
) -> None:
    response = await api.post(
        "/v1/ipm/organizations", json={"name": "ok", "ownerAccountId": "x"}, headers=authorization
    )
    assert response.status_code == 400
    assert_valid("common/api-error.v1.schema.json", response.json())
