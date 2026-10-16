"""Testes da API do Receiver de `sum.service`, com dependências simuladas (sem banco nem NATS).

O token de teste tem o formato `<sub>|<role>,<role>`: o verificador simulado devolve o
solicitante com essas roles. A verificação real de assinatura e audience está em `test_auth.py`.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from sum_service_receiver.contracts import generated
from sum_service_receiver.domain.errors import unavailable
from sum_service_receiver.domain.principal import Principal
from sum_service_receiver.domain.requests import operation_id_for
from sum_service_receiver.http.app import Dependencies, create_app
from sum_service_receiver.http.health import Health

OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
OTHER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4f"
NOW = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
ENABLE_IPM = "sum.ipm.enable"
DISABLE_IPM = "sum.ipm.disable"
GET_IPM = "sum.ipm.get"


class FakeVerifier:
    async def verify(self, token: str) -> Principal:
        subject, _, roles = token.partition("|")
        return Principal(subject, frozenset(role for role in roles.split(",") if role), token)


@dataclass
class FakeRepository:
    links: dict[str, dict[str, Any]] = field(default_factory=lambda: {})
    operations: dict[str, dict[str, Any]] = field(default_factory=lambda: {})

    async def link(self, resource_id: str) -> dict[str, Any] | None:
        return self.links.get(resource_id)

    async def links_of(self, owner_user_id: str) -> list[dict[str, Any]]:
        return [
            row for row in self.links.values() if row["desired"]["ownerUserId"] == owner_user_id
        ]

    async def active_link_for(self, owner_user_id: str, service: str) -> str | None:
        for row in self.links.values():
            desired = row["desired"]
            if (
                desired["ownerUserId"] == owner_user_id
                and desired["service"] == service
                and row["lifecycle"] == "present"
            ):
                return str(row["resource_id"])
        return None

    async def operation(self, operation_id: str) -> dict[str, Any] | None:
        return self.operations.get(operation_id)

    async def operation_of(self, resource_id: str, operation_id: str) -> dict[str, Any] | None:
        row = self.operations.get(operation_id)
        return row if row and row["resource_id"] == resource_id else None


@dataclass
class FakePublisher:
    sent: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise unavailable()
        self.sent.append((subject, json.loads(payload), message_id))


def link_row(
    resource_id: str, owner: str = OWNER, service: str = "ipm", version: str = "3"
) -> dict[str, Any]:
    desired = {
        "lifecycle": "present",
        "reconciliation": "active",
        "ownerUserId": owner,
        "service": service,
        "serviceRoles": ["ipm.organization.get"],
    }
    return {
        "resource_id": resource_id,
        "resource_version": version,
        "desired_generation": 1,
        "phase": "Ready",
        "conditions": [],
        "desired": desired,
        "observed": None,
        "lifecycle": "present",
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.fixture
def world() -> tuple[httpx.AsyncClient, FakeRepository, FakePublisher]:
    repository = FakeRepository()
    publisher = FakePublisher()
    health = Health()
    health.mark_started()
    app = create_app(Dependencies(FakeVerifier(), repository, publisher, health, lambda: NOW))  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, repository, publisher


def token(subject: str, *roles: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}|{','.join(roles)}"}


async def test_without_a_token_the_request_is_unauthorized(world: Any) -> None:
    client, _, publisher = world
    response = await client.post("/v1/sum/services", json={"service": "ipm"})
    assert response.status_code == 401 and publisher.sent == []


async def test_enabling_a_service_needs_its_enable_role_and_publishes_the_requested(
    world: Any,
) -> None:
    client, _, publisher = world
    response = await client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=token(OWNER, ENABLE_IPM)
    )
    assert response.status_code == 202
    body = response.json()
    ((subject, envelope, message_id),) = publisher.sent
    assert subject == f"receiver.requested.sum.service.{body['resourceId']}.create"
    assert message_id == body["operationId"]  # Nats-Msg-Id = operationId
    generated.MessageEnvelope.model_validate(envelope)
    assert envelope["requestedBy"] == OWNER and envelope["emitter"] == "receiver"
    assert envelope["data"]["specification"] == {"service": "ipm", "ownerUserId": OWNER}


async def test_without_the_enable_role_nothing_is_published(world: Any) -> None:
    client, _, publisher = world
    response = await client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=token(OWNER, GET_IPM)
    )
    assert response.status_code == 403 and publisher.sent == []


@pytest.mark.parametrize("service", ["IPM", "a", "ipm-x", "ip m", ""])
async def test_an_invalid_service_name_is_a_validation_error(world: Any, service: str) -> None:
    client, _, publisher = world
    response = await client.post(
        "/v1/sum/services", json={"service": service}, headers=token(OWNER, ENABLE_IPM)
    )
    assert response.status_code == 400 and response.json()["field"] == "service"
    assert publisher.sent == []


async def test_enabling_an_already_active_service_is_a_conflict_with_the_existing_id(
    world: Any,
) -> None:
    client, repository, publisher = world
    existing = str(uuid.uuid7())
    repository.links[existing] = link_row(existing)
    response = await client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=token(OWNER, ENABLE_IPM)
    )
    assert response.status_code == 409 and existing in response.json()["message"]
    assert publisher.sent == []


async def test_the_same_idempotency_key_returns_the_same_operation_and_publishes_once(
    world: Any,
) -> None:
    client, _, publisher = world
    headers = {**token(OWNER, ENABLE_IPM), "Idempotency-Key": "pedido-1"}
    first = await client.post("/v1/sum/services", json={"service": "ipm"}, headers=headers)
    assert first.status_code == 202
    operation_id = first.json()["operationId"]
    # Simula o Manager já tendo gravado a Operation desse pedido.
    world[1].operations[operation_id] = {
        "operation_id": operation_id,
        "resource_id": first.json()["resourceId"],
        "request_digest": publisher.sent[0][1]["data"]["requestDigest"],
        "requested_by": OWNER,
        "operation_type": "create",
        "operation_status": "accepted",
        "operation_status_reason": None,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": None,
    }
    second = await client.post("/v1/sum/services", json={"service": "ipm"}, headers=headers)
    assert second.status_code == 202 and second.json() == first.json()
    assert len(publisher.sent) == 1


async def test_reusing_an_idempotency_key_with_another_request_is_unprocessable(world: Any) -> None:
    client, repository, publisher = world
    headers = {**token(OWNER, ENABLE_IPM), "Idempotency-Key": "pedido-2"}
    # Operação já gravada para esta chave, com um corpo diferente do que chega agora.
    repository.operations[operation_id_for(OWNER, "pedido-2")] = {
        "request_digest": "f" * 64,
        "resource_id": "r",
    }
    response = await client.post("/v1/sum/services", json={"service": "ipm"}, headers=headers)
    assert response.status_code == 422 and publisher.sent == []


async def test_a_refused_publication_is_unavailable_with_retry_after(world: Any) -> None:
    client, _, publisher = world
    publisher.fail = True
    response = await client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=token(OWNER, ENABLE_IPM)
    )
    assert response.status_code == 503 and response.headers["Retry-After"] == "5"


async def test_the_owner_reads_its_link_with_the_get_role(world: Any) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid)
    response = await client.get(f"/v1/sum/services/{rid}", headers=token(OWNER, GET_IPM))
    assert response.status_code == 200 and response.json()["resourceId"] == rid


async def test_another_user_gets_not_found_for_a_link_that_is_not_theirs(world: Any) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid)
    response = await client.get(f"/v1/sum/services/{rid}", headers=token(OTHER, GET_IPM))
    assert response.status_code == 404


async def test_reading_without_the_get_role_is_forbidden(world: Any) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid)
    response = await client.get(f"/v1/sum/services/{rid}", headers=token(OWNER))
    assert response.status_code == 403


async def test_the_list_shows_only_the_services_the_user_can_read(world: Any) -> None:
    client, repository, _ = world
    visible = str(uuid.uuid7())
    hidden = str(uuid.uuid7())
    repository.links[visible] = link_row(visible, service="ipm")
    repository.links[hidden] = link_row(hidden, service="sum")
    response = await client.get("/v1/sum/services", headers=token(OWNER, GET_IPM))
    assert [item["resourceId"] for item in response.json()["items"]] == [visible]


async def test_disabling_without_the_version_is_a_validation_error(world: Any) -> None:
    client, repository, publisher = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid)
    response = await client.delete(f"/v1/sum/services/{rid}", headers=token(OWNER, DISABLE_IPM))
    assert response.status_code == 400 and response.json()["field"] == "resourceVersion"
    assert publisher.sent == []


async def test_disabling_with_an_outdated_version_is_a_conflict(world: Any) -> None:
    client, repository, publisher = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid, version="3")
    response = await client.delete(
        f"/v1/sum/services/{rid}?resourceVersion=2", headers=token(OWNER, DISABLE_IPM)
    )
    assert response.status_code == 409 and publisher.sent == []


async def test_disabling_publishes_the_requested_with_the_version_read(world: Any) -> None:
    client, repository, publisher = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid, version="3")
    response = await client.delete(
        f"/v1/sum/services/{rid}?resourceVersion=3", headers=token(OWNER, DISABLE_IPM)
    )
    assert response.status_code == 202
    ((subject, envelope, _),) = publisher.sent
    assert subject == f"receiver.requested.sum.service.{rid}.delete"
    assert envelope["data"]["resourceVersion"] == "3"
    generated.MessageEnvelope.model_validate(envelope)


async def test_the_operation_is_readable_only_by_who_requested_it(world: Any) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    op = str(uuid.uuid7())
    repository.operations[op] = {
        "operation_id": op,
        "resource_id": rid,
        "operation_type": "create",
        "operation_status": "accepted",
        "operation_status_reason": None,
        "request_digest": "a" * 64,
        "requested_by": OWNER,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": None,
    }
    assert (
        await client.get(f"/v1/sum/services/{rid}/operations/{op}", headers=token(OWNER))
    ).status_code == 200
    assert (
        await client.get(f"/v1/sum/services/{rid}/operations/{op}", headers=token(OTHER))
    ).status_code == 404


async def test_the_health_probes_answer(world: Any) -> None:
    client, _, _ = world
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200


# ---------------------------------------------------------------------- erros e superfície


async def test_an_invalid_body_is_400_with_the_error_contract_and_never_echoes_the_value(
    world: Any,
) -> None:
    client, _, publisher = world
    response = await client.post(
        "/v1/sum/services",
        content=b'{"service": ',
        headers={**token(OWNER, ENABLE_IPM), "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["errorCode"] == "ValidationFailed" and "detail" not in body
    assert "field" not in body  # JSON quebrado não tem campo: a posição do erro não é um campo
    assert publisher.sent == []


async def test_a_validation_error_does_not_repeat_the_sent_value(world: Any) -> None:
    client, _, _ = world
    response = await client.get(
        "/v1/sum/services?limit=valor-secreto-123", headers=token(OWNER, GET_IPM)
    )
    assert response.status_code == 400
    assert response.json()["field"] == "limit"
    assert "valor-secreto-123" not in response.text


async def test_an_unexpected_error_is_500_with_the_contract_and_no_internal_detail() -> None:
    class BrokenRepository(FakeRepository):
        async def links_of(self, owner_user_id: str) -> list[dict[str, Any]]:
            raise RuntimeError("senha-interna-do-banco")

    health = Health()
    health.mark_started()
    app = create_app(
        Dependencies(FakeVerifier(), BrokenRepository(), FakePublisher(), health, lambda: NOW)  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/sum/services", headers=token(OWNER, GET_IPM))
    assert response.status_code == 500
    assert response.json() == {"errorCode": "InternalError", "message": "Erro interno."}
    assert "senha-interna-do-banco" not in response.text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_the_interactive_documentation_is_not_exposed(world: Any, path: str) -> None:
    client, _, _ = world
    assert (await client.get(path)).status_code == 404


# ---------------------------------------------------------------------- corpos no contrato


def operation_row(
    resource_id: str, *, status: str = "accepted", generation: int | None = 2
) -> dict[str, Any]:
    rejected = status == "rejected"
    return {
        "operation_id": str(uuid.uuid7()),
        "resource_id": resource_id,
        "operation_type": "create",
        "desired_generation": None if rejected else generation,
        "operation_status": status,
        "operation_status_reason": "conflict" if rejected else None,
        "request_digest": "a" * 64,
        "requested_by": OWNER,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": NOW if rejected else None,
    }


async def test_every_success_body_matches_the_contract(world: Any) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid)
    headers = token(OWNER, ENABLE_IPM, GET_IPM, DISABLE_IPM)
    generated.ServiceResource.model_validate(
        (await client.get(f"/v1/sum/services/{rid}", headers=headers)).json()
    )
    listed = await client.get("/v1/sum/services", headers=headers)
    assert [item["resourceId"] for item in listed.json()["items"]] == [rid]
    generated.ServiceListResponse.model_validate(listed.json())
    created = await client.post(
        "/v1/sum/services", json={"service": "ipm"}, headers=token(OTHER, ENABLE_IPM)
    )
    generated.ApiAcceptedResponse.model_validate(created.json())


@pytest.mark.parametrize("status", ["accepted", "rejected"])
async def test_the_operation_body_matches_the_contract(world: Any, status: str) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    row = operation_row(rid, status=status)
    repository.operations[row["operation_id"]] = row
    response = await client.get(
        f"/v1/sum/services/{rid}/operations/{row['operation_id']}", headers=token(OWNER)
    )
    assert response.status_code == 200
    operation = generated.Operation.model_validate(response.json())
    assert (operation.module, operation.resource_type) == ("sum", "service")
    assert ("desiredGeneration" in response.json()) == (status != "rejected")


async def test_every_error_body_matches_the_contract(world: Any) -> None:
    client, repository, _ = world
    rid = str(uuid.uuid7())
    repository.links[rid] = link_row(rid)
    cases = [
        (401, await client.get("/v1/sum/services")),
        (403, await client.post("/v1/sum/services", json={"service": "ipm"}, headers=token(OTHER))),
        (404, await client.get(f"/v1/sum/services/{uuid.uuid7()}", headers=token(OWNER, GET_IPM))),
        (
            409,
            await client.post(
                "/v1/sum/services", json={"service": "ipm"}, headers=token(OWNER, ENABLE_IPM)
            ),
        ),
        (400, await client.post("/v1/sum/services", json={}, headers=token(OWNER, ENABLE_IPM))),
    ]
    for status, response in cases:
        assert response.status_code == status, response.text
        generated.ApiError.model_validate(response.json())
