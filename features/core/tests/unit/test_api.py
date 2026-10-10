import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from core.api.app import Dependencies, create_app
from core.api.errors import unauthorized
from core.api.principal import Principal
from core.api.publisher import PublishError
from core.api.ratelimit import SlidingWindowLimiter
from core.api.repository import OperationRecord, ResourceRecord
from core.api.requests import operation_id_for, request_digest
from core.contracts import generated
from core.settings import ApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER_ROLES = frozenset(
    {
        "organization.create",
        "organization.get",
        "organization.list",
        "organization.update",
        "organization.delete",
        "user.get",
        "user.delete",
    }
)
OPERATOR_ROLES = USER_ROLES | {"platform.admin"}


def principal(subject: str, roles: frozenset[str]) -> Principal:
    return Principal(subject=subject, roles=roles, access_token=f"token-{subject}")


PRINCIPALS = {
    "ana": principal("ana", USER_ROLES),
    "bia": principal("bia", USER_ROLES),
    "admin": principal("admin", OPERATOR_ROLES),
    "norole": principal("norole", frozenset()),
}


class FakeAuthenticator:
    async def verify(self, token: str) -> Principal:
        try:
            return PRINCIPALS[token]
        except KeyError:
            raise unauthorized() from None


@dataclass
class FakeEmailVerifier:
    verified: set[str] = field(default_factory=lambda: {"ana", "bia"})

    async def is_verified(self, principal: Principal) -> bool:
        return principal.subject in self.verified


@dataclass
class FakePublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError
        self.published.append((subject, json.loads(payload), message_id))


@dataclass
class FakeRepository:
    resources: dict[tuple[str, str], ResourceRecord] = field(default_factory=lambda: {})
    operations: dict[str, OperationRecord] = field(default_factory=lambda: {})
    calls: int = 0

    async def get_resource(self, resource_type: str, resource_id: str) -> ResourceRecord | None:
        self.calls += 1
        return self.resources.get((resource_type, resource_id))

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        self.calls += 1
        items = sorted(
            (r for (t, _), r in self.resources.items() if t == "organization"),
            key=lambda r: r.resource_id,
        )
        items = [r for r in items if owner is None or r.desired.get("ownerUserId") == owner]
        return [r for r in items if after is None or r.resource_id > after][:limit]

    async def count_organizations_owned_by(self, owner: str) -> int:
        self.calls += 1
        return sum(
            1
            for (t, _), r in self.resources.items()
            if t == "organization" and r.desired.get("ownerUserId") == owner
        )

    async def find_operation(
        self, operation_id: str, *, resource_type: str | None = None
    ) -> OperationRecord | None:
        self.calls += 1
        record = self.operations.get(operation_id)
        if record is not None and resource_type not in (None, record.resource_type):
            return None
        return record


def organization(
    resource_id: str, owner: str, *, name: str = "acme", version: int = 3
) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "name": name,
            "platformAccess": "granted",
            "ownerUserId": owner,
        },
        presence="present",
        observed={"name": name, "platformAccess": "granted"},
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def user_record(resource_id: str) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=2,
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "platformAccess": "granted",
            "givenName": "Ana",
            "familyName": "Souza",
            "email": "ana@example.com",
        },
        presence=None,
        observed=None,
        observed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def operation(operation_id: str, requested_by: str, *, digest: str = "d" * 64) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        resource_type="organization",
        resource_id="org-1",
        operation_type="create",
        desired_generation=1,
        request_digest=digest,
        operation_status="accepted",
        operation_status_reason=None,
        requested_by=requested_by,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )


@dataclass
class Harness:
    client: httpx.AsyncClient
    publisher: FakePublisher
    repository: FakeRepository
    emails: FakeEmailVerifier
    clock: list[float]


@pytest.fixture
def harness() -> Harness:
    counter = itertools.count(1)
    publisher, repository, emails = FakePublisher(), FakeRepository(), FakeEmailVerifier()
    clock = [0.0]
    deps = Dependencies(
        settings=ApiSettings(
            organization_quota=1, anonymous_rate_limit=3, anonymous_rate_window_seconds=60
        ),
        authenticator=FakeAuthenticator(),
        email_verifier=emails,
        repository=repository,
        publisher=publisher,
        limiter=SlidingWindowLimiter(3, 60, monotonic=lambda: clock[0]),
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, publisher, repository, emails, clock)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


# ---------------------------------------------------------------------- autenticação e autorização


async def test_health_is_public(harness: Harness) -> None:
    assert (await harness.client.get("/healthz")).json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer ruim"}, {"Authorization": "Basic x"}]
)
async def test_missing_or_invalid_token_is_401_with_the_error_contract(
    harness: Harness, headers: dict[str, str]
) -> None:
    response = await harness.client.get("/v1/organizations", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_role_is_403(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/organizations", json={"name": "acme"}, headers=auth("norole")
    )
    assert response.status_code == 403
    assert harness.publisher.published == []


# ---------------------------------------------------------------------- criar Organization


async def test_create_publishes_requested_and_answers_202(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/organizations", json={"name": "acme"}, headers=auth("ana")
    )

    assert response.status_code == 202
    body = generated.ApiAcceptedResponse.model_validate(response.json())
    ((subject, payload, message_id),) = harness.publisher.published
    assert subject == f"api.requested.core.organization.{body.resource_id}.create"
    envelope = generated.MessageEnvelope.model_validate(payload)
    assert envelope.message_id == message_id
    assert (envelope.emitter.value, envelope.message_type.value) == ("api", "requested")
    assert envelope.requested_by == "ana"
    assert envelope.data["operationId"] == body.operation_id
    assert envelope.data["specification"] == {"name": "acme", "platformAccess": "granted"}
    assert envelope.data["ownerQuotaLimit"] == 1
    assert envelope.data["requestDigest"] == request_digest(
        {"operation": "create", "specification": {"name": "acme", "platformAccess": "granted"}}
    )


async def test_operator_creates_without_quota_limit_or_verified_email(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "admin")
    response = await harness.client.post(
        "/v1/organizations", json={"name": "acme"}, headers=auth("admin")
    )
    assert response.status_code == 202
    assert "ownerQuotaLimit" not in harness.publisher.published[0][1]["data"]


async def test_unverified_email_is_403(harness: Harness) -> None:
    harness.emails.verified.clear()
    response = await harness.client.post(
        "/v1/organizations", json={"name": "acme"}, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "EmailNotVerified")
    assert harness.publisher.published == []


async def test_quota_is_checked_before_publishing(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    response = await harness.client.post(
        "/v1/organizations", json={"name": "outra"}, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "QuotaExceeded")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("body", "field_name"),
    [
        ({"name": "Nome Inválido"}, "name"),
        ({"name": "ok", "resourceId": "x"}, "resourceId"),
        ({"name": "ok", "ownerUserId": "x"}, "ownerUserId"),
        ({}, "name"),
    ],
)
async def test_invalid_body_is_400_and_does_not_echo_values(
    harness: Harness, body: dict[str, Any], field_name: str
) -> None:
    response = await harness.client.post("/v1/organizations", json=body, headers=auth("ana"))
    assert response.status_code == 400
    assert response.json()["errorCode"] == "ValidationFailed"
    assert response.json()["field"] == field_name
    assert "Inválido" not in response.text.replace("Campo inválido", "")


async def test_publish_failure_is_a_retryable_503(harness: Harness) -> None:
    harness.publisher.fail = True
    response = await harness.client.post(
        "/v1/organizations", json={"name": "acme"}, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (503, "ServiceUnavailable")
    assert response.headers["retry-after"] == "5"


# ---------------------------------------------------------------------- idempotência


async def test_idempotency_key_derives_a_stable_operation_id_per_requester(
    harness: Harness,
) -> None:
    first = await harness.client.post(
        "/v1/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    expected = operation_id_for(
        module="core", resource_type="organization", requested_by="ana", idempotency_key="k-1"
    )
    assert first.json()["operationId"] == expected
    assert expected != operation_id_for(
        module="core", resource_type="organization", requested_by="bia", idempotency_key="k-1"
    )


async def test_repeating_the_same_request_returns_the_existing_operation_without_publishing(
    harness: Harness,
) -> None:
    digest = request_digest(
        {"operation": "create", "specification": {"name": "acme", "platformAccess": "granted"}}
    )
    operation_id = operation_id_for(
        module="core", resource_type="organization", requested_by="ana", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "ana", digest=digest)

    response = await harness.client.post(
        "/v1/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    assert (response.status_code, response.json()) == (
        202,
        {"resourceId": "org-1", "operationId": operation_id},
    )
    assert harness.publisher.published == []


async def test_same_key_with_other_content_is_422(harness: Harness) -> None:
    operation_id = operation_id_for(
        module="core", resource_type="organization", requested_by="ana", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "ana", digest="f" * 64)
    response = await harness.client.post(
        "/v1/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    assert (response.status_code, response.json()["errorCode"]) == (422, "IdempotencyKeyReused")


async def test_invalid_idempotency_key_is_400(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "chave invalida!"},
    )
    assert (response.status_code, response.json()["field"]) == (400, "Idempotency-Key")


# ---------------------------------------------------------------------- ler Organization


async def test_owner_reads_the_organization_without_the_owner_field(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    response = await harness.client.get("/v1/organizations/o-1", headers=auth("ana"))
    assert response.status_code == 200
    view = generated.Organization.model_validate(response.json())
    assert (view.resource_id, view.resource_version, view.phase.value) == ("o-1", "3", "Ready")
    assert "ownerUserId" not in response.text


async def test_other_users_organization_is_404_and_operator_can_read(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    assert (
        await harness.client.get("/v1/organizations/o-1", headers=auth("bia"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/organizations/ghost", headers=auth("ana"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/organizations/o-1", headers=auth("admin"))
    ).status_code == 200


async def test_list_is_scoped_to_the_owner_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[("organization", f"a-{index}")] = organization(
            f"a-{index}", "ana"
        )
    harness.repository.resources[("organization", "b-0")] = organization("b-0", "bia")

    first = (await harness.client.get("/v1/organizations?limit=2", headers=auth("ana"))).json()
    assert [item["resourceId"] for item in first["items"]] == ["a-0", "a-1"]
    second = (
        await harness.client.get(
            f"/v1/organizations?limit=2&cursor={first['nextCursor']}", headers=auth("ana")
        )
    ).json()
    assert [item["resourceId"] for item in second["items"]] == ["a-2"]
    assert "nextCursor" not in second

    everything = (await harness.client.get("/v1/organizations", headers=auth("admin"))).json()
    assert len(everything["items"]) == 4
    assert (
        await harness.client.get("/v1/organizations?limit=0", headers=auth("ana"))
    ).status_code == 400
    assert (
        await harness.client.get("/v1/organizations?limit=201", headers=auth("ana"))
    ).status_code == 400


# ---------------------------------------------------------------------- alterar e remover


async def test_update_publishes_with_the_resource_version(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    response = await harness.client.patch(
        "/v1/organizations/o-1", json={"resourceVersion": "3", "name": "novo"}, headers=auth("ana")
    )
    assert response.status_code == 202
    subject, payload, _ = harness.publisher.published[0]
    assert subject == "api.requested.core.organization.o-1.update"
    assert payload["data"]["resourceVersion"] == "3"
    assert payload["data"]["specification"] == {"name": "novo"}


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"resourceVersion": "2", "name": "novo"}, 409),
        ({"resourceVersion": "3", "platformAccess": "revoked"}, 403),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, 403),
        ({"resourceVersion": "3"}, 400),
        ({"resourceVersion": "abc", "name": "novo"}, 400),
    ],
)
async def test_update_rules(harness: Harness, body: dict[str, Any], status: int) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    response = await harness.client.patch("/v1/organizations/o-1", json=body, headers=auth("ana"))
    assert response.status_code == status
    assert harness.publisher.published == []


async def test_operator_may_change_platform_access_and_reconciliation(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    response = await harness.client.patch(
        "/v1/organizations/o-1",
        json={"resourceVersion": "3", "platformAccess": "revoked", "reconciliation": "suspended"},
        headers=auth("admin"),
    )
    assert response.status_code == 202


async def test_delete_requires_the_version_and_the_owner(harness: Harness) -> None:
    harness.repository.resources[("organization", "o-1")] = organization("o-1", "ana")
    assert (
        await harness.client.delete("/v1/organizations/o-1", headers=auth("ana"))
    ).status_code == 400
    assert (
        await harness.client.delete("/v1/organizations/o-1?resourceVersion=1", headers=auth("ana"))
    ).status_code == 409
    assert (
        await harness.client.delete("/v1/organizations/o-1?resourceVersion=3", headers=auth("bia"))
    ).status_code == 404
    ok = await harness.client.delete("/v1/organizations/o-1?resourceVersion=3", headers=auth("ana"))
    assert ok.status_code == 202
    assert harness.publisher.published[0][0] == "api.requested.core.organization.o-1.delete"


# ---------------------------------------------------------------------- cadastro anônimo


REGISTRATION = {"givenName": "Ana", "familyName": "Souza", "email": "ana@example.com"}


async def test_registration_is_anonymous_uniform_and_never_touches_the_ssot(
    harness: Harness,
) -> None:
    response = await harness.client.post("/v1/users", json=REGISTRATION)
    again = await harness.client.post("/v1/users", json=REGISTRATION)

    assert (response.status_code, again.status_code) == (202, 202)
    assert set(response.json()) == set(again.json()) == {"resourceId", "operationId"}
    assert harness.repository.calls == 0  # sem consulta: nada revela se o e-mail já existe
    subject, payload, _ = harness.publisher.published[0]
    assert subject.startswith("api.requested.core.user.") and subject.endswith(".create")
    assert payload["requestedBy"] == "anonymous"
    assert payload["data"]["specification"] == REGISTRATION


@pytest.mark.parametrize(
    "extra", [{"password": "Segredo!123"}, {"resourceId": "x"}, {"requestedBy": "admin"}]
)
async def test_registration_rejects_password_and_server_fields(
    harness: Harness, extra: dict[str, str]
) -> None:
    response = await harness.client.post("/v1/users", json={**REGISTRATION, **extra})
    assert response.status_code == 400
    assert "Segredo" not in response.text
    assert harness.publisher.published == []


async def test_registration_is_rate_limited_by_the_gateway_supplied_origin(
    harness: Harness,
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.2"}
    statuses = [
        (await harness.client.post("/v1/users", json=REGISTRATION, headers=headers)).status_code
        for _ in range(4)
    ]
    assert statuses == [202, 202, 202, 429]
    limited = await harness.client.post("/v1/users", json=REGISTRATION, headers=headers)
    assert limited.json()["errorCode"] == "RateLimited"
    assert int(limited.headers["retry-after"]) >= 1
    # outra origem não é afetada; o valor forjado à esquerda não muda a origem
    other = {"X-Forwarded-For": "198.51.100.1, 10.0.0.9"}
    assert (
        await harness.client.post("/v1/users", json=REGISTRATION, headers=other)
    ).status_code == 202
    forged = {"X-Forwarded-For": "1.2.3.4, 10.0.0.2"}
    assert (
        await harness.client.post("/v1/users", json=REGISTRATION, headers=forged)
    ).status_code == 429
    harness.clock[0] = 61.0
    assert (
        await harness.client.post("/v1/users", json=REGISTRATION, headers=headers)
    ).status_code == 202


# ---------------------------------------------------------------------- User


async def test_user_reads_and_deletes_only_itself(harness: Harness) -> None:
    harness.repository.resources[("user", "ana")] = user_record("ana")
    own = await harness.client.get("/v1/users/ana", headers=auth("ana"))
    assert own.status_code == 200
    assert generated.User.model_validate(own.json()).desired.email is not None
    assert (await harness.client.get("/v1/users/ana", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get("/v1/users/ana", headers=auth("admin"))).status_code == 200

    assert (
        await harness.client.delete("/v1/users/ana?resourceVersion=2", headers=auth("bia"))
    ).status_code == 404
    deleted = await harness.client.delete("/v1/users/ana?resourceVersion=2", headers=auth("ana"))
    assert deleted.status_code == 202
    assert harness.publisher.published[0][0] == "api.requested.core.user.ana.delete"


# ---------------------------------------------------------------------- Operation


async def test_operation_is_readable_only_by_the_requester_and_operators(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "ana")
    harness.repository.operations["op-anon"] = operation("op-anon", "anonymous")

    own = await harness.client.get("/v1/operations/op-1", headers=auth("ana"))
    assert own.status_code == 200
    generated.Operation.model_validate(own.json())
    assert "requestedBy" not in own.text
    assert (await harness.client.get("/v1/operations/op-1", headers=auth("bia"))).status_code == 404
    assert (
        await harness.client.get("/v1/operations/op-1", headers=auth("admin"))
    ).status_code == 200
    assert (
        await harness.client.get("/v1/operations/op-anon", headers=auth("ana"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/operations/op-anon", headers=auth("admin"))
    ).status_code == 200
    assert (
        await harness.client.get("/v1/operations/ghost", headers=auth("ana"))
    ).status_code == 404
    assert (await harness.client.get("/v1/operations/op-1")).status_code == 401
