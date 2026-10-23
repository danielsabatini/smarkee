import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ipm_organization.common.contracts import generated
from ipm_organization.common.ports import PublishError
from ipm_organization.receiver.domain.errors import unauthorized
from ipm_organization.receiver.domain.principal import Principal
from ipm_organization.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_organization.receiver.domain.requests import operation_id_for, request_digest
from ipm_organization.receiver.domain.users import BillingAccountCheckError, UsersCheckError
from ipm_organization.receiver.http.app import Dependencies, create_app
from ipm_organization.receiver.settings import ApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER_ROLES = frozenset(
    {
        "ipm.organization.create",
        "ipm.organization.get",
        "ipm.organization.list",
        "ipm.organization.update",
        "ipm.organization.delete",
    }
)
OPERATOR_ROLES = USER_ROLES | {"ipm.organization.admin"}


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
class FakeUsers:
    """Receiver do User e do Billing Account."""

    members: dict[str, str] = field(default_factory=lambda: {})
    populated: set[str] = field(default_factory=lambda: set())
    ready_billing_accounts: set[str] = field(default_factory=lambda: {"ba-ready"})
    error: UsersCheckError | None = None
    billing_error: BillingAccountCheckError | None = None

    async def organization_of(self, user_id: str, access_token: str) -> str | None:
        if self.error is not None:
            raise self.error
        return self.members.get(user_id)

    async def has_users(self, organization_id: str, access_token: str) -> bool:
        if self.error is not None:
            raise self.error
        return organization_id in self.populated

    async def is_ready_billing_account(self, billing_account_id: str, access_token: str) -> bool:
        if self.billing_error is not None:
            raise self.billing_error
        return billing_account_id in self.ready_billing_accounts


@dataclass
class FakePublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError("unavailable")
        self.published.append((subject, json.loads(payload), message_id))


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})
    operations: dict[str, OperationRecord] = field(default_factory=lambda: {})
    calls: int = 0

    async def get_organization(self, resource_id: str) -> ResourceRecord | None:
        self.calls += 1
        return self.resources.get(resource_id)

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        self.calls += 1
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        items = [r for r in items if owner is None or r.desired.get("ownerAccountId") == owner]
        return [r for r in items if after is None or r.resource_id > after][:limit]

    async def count_organizations_owned_by(self, owner: str) -> int:
        self.calls += 1
        return sum(1 for r in self.resources.values() if r.desired.get("ownerAccountId") == owner)

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        self.calls += 1
        return self.operations.get(operation_id)


def organization(
    resource_id: str,
    owner: str,
    *,
    name: str = "acme",
    version: int = 3,
    protected: bool | None = False,
) -> ResourceRecord:
    """`protected=None` simula o registro anterior à proteção (sem o campo)."""
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "name": name,
        "platformAccess": "granted",
        "ownerAccountId": owner,
    }
    if protected is not None:
        desired["deletionProtection"] = protected
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=desired,
        presence="present",
        observed={"name": name, "platformAccess": "granted"},
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def operation(operation_id: str, requested_by: str, *, digest: str = "d" * 64) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
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
    users: FakeUsers


@pytest.fixture
def harness() -> Harness:
    counter = itertools.count(1)
    publisher, repository, emails = FakePublisher(), FakeRepository(), FakeEmailVerifier()
    users = FakeUsers()
    deps = Dependencies(
        settings=ApiSettings(organization_quota=1),
        authenticator=FakeAuthenticator(),
        email_verifier=emails,
        repository=repository,
        users=users,
        publisher=publisher,
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, publisher, repository, emails, users)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


# ---------------------------------------------------------------------- autenticação e autorização


async def test_health_probes_are_public_and_readiness_reflects_the_dependencies(
    harness: Harness,
) -> None:
    for probe in ("live", "startup", "ready"):
        response = await harness.client.get(f"/health/{probe}")
        assert response.status_code == 200
        assert response.json()["status"] == "UP"


async def test_readiness_is_down_when_a_critical_dependency_is_down() -> None:
    deps = Dependencies(
        settings=ApiSettings(),
        authenticator=FakeAuthenticator(),
        email_verifier=FakeEmailVerifier(),
        repository=FakeRepository(),
        users=FakeUsers(),
        publisher=FakePublisher(),
        is_ready=lambda: False,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    ready = await client.get("/health/ready")
    assert ready.status_code == 503 and ready.json()["status"] == "DOWN"
    assert (await client.get("/health/live")).status_code == 200  # a liveness não olha o NATS


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer ruim"}, {"Authorization": "Basic x"}]
)
async def test_missing_or_invalid_token_is_401_with_the_error_contract(
    harness: Harness, headers: dict[str, str]
) -> None:
    response = await harness.client.get("/v1/ipm/organizations", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_role_is_403(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/ipm/organizations", json={"name": "acme"}, headers=auth("norole")
    )
    assert response.status_code == 403
    assert harness.publisher.published == []


# ---------------------------------------------------------------------- criar Organization


async def test_create_publishes_requested_and_answers_202(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/ipm/organizations", json={"name": "acme"}, headers=auth("ana")
    )

    assert response.status_code == 202
    body = generated.ApiAcceptedResponse.model_validate(response.json())
    ((subject, payload, message_id),) = harness.publisher.published
    assert subject == f"receiver.requested.ipm.organization.{body.resource_id}.create"
    envelope = generated.MessageEnvelope.model_validate(payload)
    assert envelope.message_id == message_id
    assert (envelope.emitter.value, envelope.message_type.value) == ("receiver", "requested")
    assert envelope.requested_by == "ana"
    assert envelope.data["operationId"] == body.operation_id
    assert envelope.data["specification"] == {"name": "acme", "platformAccess": "granted"}
    assert envelope.data["ownerQuotaLimit"] == 1
    assert envelope.data["requestDigest"] == request_digest(
        {"operation": "create", "specification": {"name": "acme", "platformAccess": "granted"}}
    )


async def test_operator_creates_without_quota_limit_or_verified_email(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "admin")
    response = await harness.client.post(
        "/v1/ipm/organizations", json={"name": "acme"}, headers=auth("admin")
    )
    assert response.status_code == 202
    assert "ownerQuotaLimit" not in harness.publisher.published[0][1]["data"]


async def test_unverified_email_is_403(harness: Harness) -> None:
    harness.emails.verified.clear()
    response = await harness.client.post(
        "/v1/ipm/organizations", json={"name": "acme"}, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "EmailNotVerified")
    assert harness.publisher.published == []


async def test_quota_is_checked_before_publishing(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    response = await harness.client.post(
        "/v1/ipm/organizations", json={"name": "outra"}, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "QuotaExceeded")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("body", "field_name"),
    [
        ({"name": "Nome Inválido"}, "name"),
        ({"name": "ok", "resourceId": "x"}, "resourceId"),
        ({"name": "ok", "ownerAccountId": "x"}, "ownerAccountId"),
        ({}, "name"),
    ],
)
async def test_invalid_body_is_400_and_does_not_echo_values(
    harness: Harness, body: dict[str, Any], field_name: str
) -> None:
    response = await harness.client.post("/v1/ipm/organizations", json=body, headers=auth("ana"))
    assert response.status_code == 400
    assert response.json()["errorCode"] == "ValidationFailed"
    assert response.json()["field"] == field_name
    assert "Inválido" not in response.text.replace("Campo inválido", "")


async def test_publish_failure_is_a_retryable_503(harness: Harness) -> None:
    harness.publisher.fail = True
    response = await harness.client.post(
        "/v1/ipm/organizations", json={"name": "acme"}, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (503, "ServiceUnavailable")
    assert response.headers["retry-after"] == "5"


# ---------------------------------------------------------------------- idempotência


async def test_idempotency_key_derives_a_stable_operation_id_per_requester(
    harness: Harness,
) -> None:
    first = await harness.client.post(
        "/v1/ipm/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    expected = operation_id_for(
        module="ipm", resource_type="organization", requested_by="ana", idempotency_key="k-1"
    )
    assert first.json()["operationId"] == expected
    assert expected != operation_id_for(
        module="ipm", resource_type="organization", requested_by="bia", idempotency_key="k-1"
    )


async def test_repeating_the_same_request_returns_the_existing_operation_without_publishing(
    harness: Harness,
) -> None:
    digest = request_digest(
        {"operation": "create", "specification": {"name": "acme", "platformAccess": "granted"}}
    )
    operation_id = operation_id_for(
        module="ipm", resource_type="organization", requested_by="ana", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "ana", digest=digest)

    response = await harness.client.post(
        "/v1/ipm/organizations",
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
        module="ipm", resource_type="organization", requested_by="ana", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "ana", digest="f" * 64)
    response = await harness.client.post(
        "/v1/ipm/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    assert (response.status_code, response.json()["errorCode"]) == (422, "IdempotencyKeyReused")


async def test_invalid_idempotency_key_is_400(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/ipm/organizations",
        json={"name": "acme"},
        headers={**auth("ana"), "Idempotency-Key": "chave invalida!"},
    )
    assert (response.status_code, response.json()["field"]) == (400, "Idempotency-Key")


# ---------------------------------------------------------------------- ler Organization


async def test_owner_reads_the_organization_without_the_owner_field(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    response = await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("ana"))
    assert response.status_code == 200
    view = generated.Organization.model_validate(response.json())
    assert (view.resource_id, view.resource_version, view.phase.value) == ("o-1", "3", "Ready")
    assert "ownerAccountId" not in response.text


async def test_other_users_organization_is_404_and_operator_can_read(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    assert (
        await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("bia"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/ipm/organizations/ghost", headers=auth("ana"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("admin"))
    ).status_code == 200


async def test_list_is_scoped_to_the_owner_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[f"a-{index}"] = organization(f"a-{index}", "ana")
    harness.repository.resources["b-0"] = organization("b-0", "bia")

    first = (await harness.client.get("/v1/ipm/organizations?limit=2", headers=auth("ana"))).json()
    assert [item["resourceId"] for item in first["items"]] == ["a-0", "a-1"]
    second = (
        await harness.client.get(
            f"/v1/ipm/organizations?limit=2&cursor={first['nextCursor']}", headers=auth("ana")
        )
    ).json()
    assert [item["resourceId"] for item in second["items"]] == ["a-2"]
    assert "nextCursor" not in second

    everything = (await harness.client.get("/v1/ipm/organizations", headers=auth("admin"))).json()
    assert len(everything["items"]) == 4
    assert (
        await harness.client.get("/v1/ipm/organizations?limit=0", headers=auth("ana"))
    ).status_code == 400
    assert (
        await harness.client.get("/v1/ipm/organizations?limit=201", headers=auth("ana"))
    ).status_code == 400


# ---------------------------------------------------------------------- alterar e remover


async def test_update_publishes_with_the_resource_version(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    response = await harness.client.patch(
        "/v1/ipm/organizations/o-1",
        json={"resourceVersion": "3", "name": "novo"},
        headers=auth("ana"),
    )
    assert response.status_code == 202
    subject, payload, _ = harness.publisher.published[0]
    assert subject == "receiver.requested.ipm.organization.o-1.update"
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
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    response = await harness.client.patch(
        "/v1/ipm/organizations/o-1", json=body, headers=auth("ana")
    )
    assert response.status_code == status
    assert harness.publisher.published == []


async def test_operator_may_change_platform_access_and_reconciliation(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    response = await harness.client.patch(
        "/v1/ipm/organizations/o-1",
        json={"resourceVersion": "3", "platformAccess": "revoked", "reconciliation": "suspended"},
        headers=auth("admin"),
    )
    assert response.status_code == 202


async def test_delete_requires_the_version_and_the_owner(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    assert (
        await harness.client.delete("/v1/ipm/organizations/o-1", headers=auth("ana"))
    ).status_code == 400
    assert (
        await harness.client.delete(
            "/v1/ipm/organizations/o-1?resourceVersion=1", headers=auth("ana")
        )
    ).status_code == 409
    assert (
        await harness.client.delete(
            "/v1/ipm/organizations/o-1?resourceVersion=3", headers=auth("bia")
        )
    ).status_code == 404
    ok = await harness.client.delete(
        "/v1/ipm/organizations/o-1?resourceVersion=3", headers=auth("ana")
    )
    assert ok.status_code == 202
    assert harness.publisher.published[0][0] == "receiver.requested.ipm.organization.o-1.delete"


@pytest.mark.parametrize("protected", [True, None])
async def test_delete_of_a_protected_organization_is_refused(
    harness: Harness, protected: bool | None
) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana", protected=protected)
    response = await harness.client.delete(
        "/v1/ipm/organizations/o-1?resourceVersion=3", headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "DeletionProtected"
    assert harness.publisher.published == []


async def test_owner_may_change_deletion_protection(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana", protected=True)
    response = await harness.client.patch(
        "/v1/ipm/organizations/o-1",
        json={"resourceVersion": "3", "deletionProtection": False},
        headers=auth("ana"),
    )
    assert response.status_code == 202
    assert harness.publisher.published[0][1]["data"]["specification"] == {
        "deletionProtection": False
    }


async def test_view_exposes_deletion_protection_and_defaults_to_protected(
    harness: Harness,
) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana", protected=None)
    harness.repository.resources["o-2"] = organization("o-2", "ana", protected=False)
    first = await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("ana"))
    second = await harness.client.get("/v1/ipm/organizations/o-2", headers=auth("ana"))
    assert first.json()["desired"]["deletionProtection"] is True
    assert second.json()["desired"]["deletionProtection"] is False


# ---------------------------------------------------------------------- Operation


async def test_operation_is_readable_only_by_the_requester_and_operators(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "ana")
    harness.repository.operations["op-anon"] = operation("op-anon", "anonymous")
    path = "/v1/ipm/organizations/org-1/operations"

    own = await harness.client.get(f"{path}/op-1", headers=auth("ana"))
    assert own.status_code == 200
    generated.Operation.model_validate(own.json())
    assert "requestedBy" not in own.text
    assert (await harness.client.get(f"{path}/op-1", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-1", headers=auth("admin"))).status_code == 200
    assert (await harness.client.get(f"{path}/op-anon", headers=auth("ana"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-anon", headers=auth("admin"))).status_code == 200
    assert (await harness.client.get(f"{path}/ghost", headers=auth("ana"))).status_code == 404
    assert (await harness.client.get(f"{path}/op-1")).status_code == 401


async def test_operation_of_another_resource_is_404(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "ana")
    response = await harness.client.get(
        "/v1/ipm/organizations/outra/operations/op-1", headers=auth("ana")
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------- usuários da Organization


async def test_a_user_of_the_organization_reads_and_lists_only_it(harness: Harness) -> None:
    """Usuário da Organization (decisão 0077): reconhecido pelo Receiver do User."""
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    harness.repository.resources["o-2"] = organization("o-2", "ana", name="outra")
    harness.users.members["bia"] = "o-1"
    assert (
        await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("bia"))
    ).status_code == 200
    assert (
        await harness.client.get("/v1/ipm/organizations/o-2", headers=auth("bia"))
    ).status_code == 404
    listed = await harness.client.get("/v1/ipm/organizations", headers=auth("bia"))
    assert [item["resourceId"] for item in listed.json()["items"]] == ["o-1"]


async def test_the_owner_is_recognized_without_asking_the_users(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    harness.users.error = UsersCheckError(retryable=True)
    assert (
        await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("ana"))
    ).status_code == 200
    other = await harness.client.get("/v1/ipm/organizations/o-1", headers=auth("bia"))
    assert (other.status_code, other.headers["retry-after"]) == (503, "5")


async def test_delete_is_refused_while_the_organization_has_users(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana", protected=False)
    harness.users.populated.add("o-1")
    response = await harness.client.delete(
        "/v1/ipm/organizations/o-1?resourceVersion=3", headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (409, "ResourcesAttached")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("retryable", "status", "code"),
    [(True, 503, "UsersUnavailable"), (False, 409, "ResourcesNotVerifiable")],
)
async def test_delete_does_not_proceed_when_the_users_cannot_be_verified(
    harness: Harness, retryable: bool, status: int, code: str
) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana", protected=False)
    harness.users.error = UsersCheckError(retryable=retryable)
    response = await harness.client.delete(
        "/v1/ipm/organizations/o-1?resourceVersion=3", headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (status, code)
    assert harness.publisher.published == []


async def test_create_accepts_a_ready_billing_account_and_refuses_an_unready_one(
    harness: Harness,
) -> None:
    refused = await harness.client.post(
        "/v1/ipm/organizations",
        json={"name": "acme", "billingAccountId": "ba-missing"},
        headers=auth("ana"),
    )
    assert (refused.status_code, refused.json()["errorCode"]) == (409, "BillingAccountNotReady")
    assert harness.publisher.published == []

    accepted = await harness.client.post(
        "/v1/ipm/organizations",
        json={"name": "acme", "billingAccountId": "ba-ready"},
        headers=auth("ana"),
    )
    assert accepted.status_code == 202
    assert harness.publisher.published[0][1]["data"]["specification"]["billingAccountId"] == (
        "ba-ready"
    )


async def test_update_validates_the_billing_account_when_provided(harness: Harness) -> None:
    harness.repository.resources["o-1"] = organization("o-1", "ana")
    refused = await harness.client.patch(
        "/v1/ipm/organizations/o-1",
        json={"resourceVersion": "3", "billingAccountId": "ba-missing"},
        headers=auth("ana"),
    )
    assert (refused.status_code, refused.json()["errorCode"]) == (409, "BillingAccountNotReady")

    accepted = await harness.client.patch(
        "/v1/ipm/organizations/o-1",
        json={"resourceVersion": "3", "billingAccountId": "ba-ready"},
        headers=auth("ana"),
    )
    assert accepted.status_code == 202
    assert harness.publisher.published[0][1]["data"]["specification"]["billingAccountId"] == (
        "ba-ready"
    )


@pytest.mark.parametrize(
    ("retryable", "status", "code"),
    [(True, 503, "BillingAccountsUnavailable"), (False, 409, "ResourcesNotVerifiable")],
)
async def test_create_with_billing_account_fails_when_bsm_cannot_be_verified(
    harness: Harness, retryable: bool, status: int, code: str
) -> None:
    harness.users.billing_error = BillingAccountCheckError(retryable=retryable)
    response = await harness.client.post(
        "/v1/ipm/organizations",
        json={"name": "acme", "billingAccountId": "ba-ready"},
        headers=auth("ana"),
    )
    assert (response.status_code, response.json()["errorCode"]) == (status, code)
    assert harness.publisher.published == []
