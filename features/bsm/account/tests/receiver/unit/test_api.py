import itertools
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from bsm_account.common.contracts import generated
from bsm_account.common.ports import PublishError
from bsm_account.receiver.domain.errors import unauthorized
from bsm_account.receiver.domain.organizations import OrganizationsCheckError
from bsm_account.receiver.domain.principal import Principal
from bsm_account.receiver.domain.records import OperationRecord, ResourceRecord
from bsm_account.receiver.domain.requests import operation_id_for, request_digest
from bsm_account.receiver.http.app import Dependencies, create_app
from bsm_account.receiver.settings import ApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER_ROLES = frozenset(
    {
        "bsm.account.create",
        "bsm.account.get",
        "bsm.account.list",
        "bsm.account.update",
        "bsm.account.delete",
    }
)
OPERATOR_ROLES = USER_ROLES | {"bsm.account.admin"}


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
            raise PublishError("unavailable")
        self.published.append((subject, json.loads(payload), message_id))


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})
    operations: dict[str, OperationRecord] = field(default_factory=lambda: {})
    calls: int = 0

    async def get_account(self, resource_id: str) -> ResourceRecord | None:
        self.calls += 1
        return self.resources.get(resource_id)

    async def list_accounts(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        self.calls += 1
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        items = [r for r in items if owner is None or r.desired.get("ownerAccountId") == owner]
        return [r for r in items if after is None or r.resource_id > after][:limit]

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        self.calls += 1
        return self.operations.get(operation_id)


def account_record(
    resource_id: str,
    owner: str,
    *,
    display_name: str = "Produção Brasil",
    currency: str = "BRL",
    contacts: list[str] | None = None,
    version: int = 3,
    protected: bool | None = False,
) -> ResourceRecord:
    """`protected=None` simula o registro anterior à proteção (sem o campo)."""
    contact_list = contacts if contacts is not None else ["finops@acme.example"]
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "displayName": display_name,
        "billingCurrency": currency,
        "billingContacts": contact_list,
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
        observed={
            "displayName": display_name,
            "billingCurrency": currency,
            "billingContacts": contact_list,
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def operation(operation_id: str, requested_by: str, *, digest: str = "d" * 64) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id,
        resource_id="ba-1",
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
class FakeOrganizations:
    attached: set[str] = field(default_factory=lambda: set())
    error: OrganizationsCheckError | None = None

    async def has_organizations(self, billing_account_id: str, access_token: str) -> bool:
        if self.error is not None:
            raise self.error
        return billing_account_id in self.attached


@dataclass
class Harness:
    client: httpx.AsyncClient
    publisher: FakePublisher
    repository: FakeRepository
    emails: FakeEmailVerifier
    organizations: FakeOrganizations


@pytest.fixture
def harness() -> Harness:
    counter = itertools.count(1)
    publisher, repository, emails = FakePublisher(), FakeRepository(), FakeEmailVerifier()
    organizations = FakeOrganizations()
    deps = Dependencies(
        settings=ApiSettings(),
        authenticator=FakeAuthenticator(),
        email_verifier=emails,
        repository=repository,
        organizations=organizations,
        publisher=publisher,
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, publisher, repository, emails, organizations)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


CREATE_PAYLOAD: dict[str, Any] = {
    "displayName": "Produção Brasil",
    "billingCurrency": "BRL",
    "billingContacts": ["finops@acme.example"],
}


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
        organizations=FakeOrganizations(),
        publisher=FakePublisher(),
        is_ready=lambda: False,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    ready = await client.get("/health/ready")
    assert ready.status_code == 503 and ready.json()["status"] == "DOWN"
    assert (await client.get("/health/live")).status_code == 200


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer ruim"}, {"Authorization": "Basic x"}]
)
async def test_missing_or_invalid_token_is_401_with_the_error_contract(
    harness: Harness, headers: dict[str, str]
) -> None:
    response = await harness.client.get("/v1/bsm/accounts", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_role_is_403(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/bsm/accounts", json=CREATE_PAYLOAD, headers=auth("norole")
    )
    assert response.status_code == 403
    assert harness.publisher.published == []


# ---------------------------------------------------------------------- criar Billing Account


async def test_create_publishes_requested_and_answers_202(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/bsm/accounts", json=CREATE_PAYLOAD, headers=auth("ana")
    )

    assert response.status_code == 202
    body = generated.ApiAcceptedResponse.model_validate(response.json())
    ((subject, payload, message_id),) = harness.publisher.published
    assert subject == f"receiver.requested.bsm.account.{body.resource_id}.create"
    envelope = generated.MessageEnvelope.model_validate(payload)
    assert envelope.message_id == message_id
    assert (envelope.emitter.value, envelope.message_type.value) == ("receiver", "requested")
    assert envelope.requested_by == "ana"
    assert envelope.data["operationId"] == body.operation_id
    assert envelope.data["specification"] == CREATE_PAYLOAD
    assert envelope.data["requestDigest"] == request_digest(
        {"operation": "create", "specification": CREATE_PAYLOAD}
    )


async def test_operator_creates_without_verified_email(harness: Harness) -> None:
    harness.emails.verified.clear()
    response = await harness.client.post(
        "/v1/bsm/accounts", json=CREATE_PAYLOAD, headers=auth("admin")
    )
    assert response.status_code == 202


async def test_unverified_email_is_403(harness: Harness) -> None:
    harness.emails.verified.clear()
    response = await harness.client.post(
        "/v1/bsm/accounts", json=CREATE_PAYLOAD, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "EmailNotVerified")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("body", "field_name"),
    [
        ({**CREATE_PAYLOAD, "displayName": ""}, "displayName"),
        ({**CREATE_PAYLOAD, "billingCurrency": "JPY"}, "billingCurrency"),
        ({**CREATE_PAYLOAD, "billingContacts": []}, "billingContacts"),
        (
            {
                **CREATE_PAYLOAD,
                "billingContacts": ["finops@acme.example", "finops@acme.example"],
            },
            "billingContacts",
        ),
        ({**CREATE_PAYLOAD, "resourceId": "x"}, "resourceId"),
        ({**CREATE_PAYLOAD, "ownerAccountId": "x"}, "ownerAccountId"),
        ({}, "displayName"),
    ],
)
async def test_invalid_body_is_400_and_does_not_echo_values(
    harness: Harness, body: dict[str, Any], field_name: str
) -> None:
    response = await harness.client.post("/v1/bsm/accounts", json=body, headers=auth("ana"))
    assert response.status_code == 400
    assert response.json()["errorCode"] == "ValidationFailed"
    assert response.json()["field"] == field_name


async def test_publish_failure_is_a_retryable_503(harness: Harness) -> None:
    harness.publisher.fail = True
    response = await harness.client.post(
        "/v1/bsm/accounts", json=CREATE_PAYLOAD, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (503, "ServiceUnavailable")
    assert response.headers["retry-after"] == "5"


# ---------------------------------------------------------------------- idempotência


async def test_idempotency_key_derives_a_stable_operation_id_per_requester(
    harness: Harness,
) -> None:
    first = await harness.client.post(
        "/v1/bsm/accounts",
        json=CREATE_PAYLOAD,
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    expected = operation_id_for(
        module="bsm", resource_type="account", requested_by="ana", idempotency_key="k-1"
    )
    assert first.json()["operationId"] == expected
    assert expected != operation_id_for(
        module="bsm", resource_type="account", requested_by="bia", idempotency_key="k-1"
    )


async def test_repeating_the_same_request_returns_the_existing_operation_without_publishing(
    harness: Harness,
) -> None:
    digest = request_digest({"operation": "create", "specification": CREATE_PAYLOAD})
    operation_id = operation_id_for(
        module="bsm", resource_type="account", requested_by="ana", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "ana", digest=digest)

    response = await harness.client.post(
        "/v1/bsm/accounts",
        json=CREATE_PAYLOAD,
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    assert (response.status_code, response.json()) == (
        202,
        {"resourceId": "ba-1", "operationId": operation_id},
    )
    assert harness.publisher.published == []


async def test_same_key_with_other_content_is_422(harness: Harness) -> None:
    operation_id = operation_id_for(
        module="bsm", resource_type="account", requested_by="ana", idempotency_key="k-1"
    )
    harness.repository.operations[operation_id] = operation(operation_id, "ana", digest="f" * 64)
    response = await harness.client.post(
        "/v1/bsm/accounts",
        json=CREATE_PAYLOAD,
        headers={**auth("ana"), "Idempotency-Key": "k-1"},
    )
    assert (response.status_code, response.json()["errorCode"]) == (422, "IdempotencyKeyReused")


async def test_invalid_idempotency_key_is_400(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/bsm/accounts",
        json=CREATE_PAYLOAD,
        headers={**auth("ana"), "Idempotency-Key": "chave invalida!"},
    )
    assert (response.status_code, response.json()["field"]) == (400, "Idempotency-Key")


# ---------------------------------------------------------------------- ler Billing Account


async def test_owner_reads_the_account_without_the_owner_field(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana")
    response = await harness.client.get("/v1/bsm/accounts/ba-1", headers=auth("ana"))
    assert response.status_code == 200
    view = generated.BillingAccount.model_validate(response.json())
    assert (view.resource_id, view.resource_version, view.phase.value) == ("ba-1", "3", "Ready")
    assert "ownerAccountId" not in response.text


async def test_other_users_account_is_404_and_operator_can_read(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana")
    assert (
        await harness.client.get("/v1/bsm/accounts/ba-1", headers=auth("bia"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/bsm/accounts/ghost", headers=auth("ana"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/bsm/accounts/ba-1", headers=auth("admin"))
    ).status_code == 200


async def test_list_is_scoped_to_the_owner_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[f"a-{index}"] = account_record(f"a-{index}", "ana")
    harness.repository.resources["b-0"] = account_record("b-0", "bia")

    first = (await harness.client.get("/v1/bsm/accounts?limit=2", headers=auth("ana"))).json()
    assert [item["resourceId"] for item in first["items"]] == ["a-0", "a-1"]
    second = (
        await harness.client.get(
            f"/v1/bsm/accounts?limit=2&cursor={first['nextCursor']}", headers=auth("ana")
        )
    ).json()
    assert [item["resourceId"] for item in second["items"]] == ["a-2"]
    assert "nextCursor" not in second

    everything = (await harness.client.get("/v1/bsm/accounts", headers=auth("admin"))).json()
    assert len(everything["items"]) == 4
    assert (
        await harness.client.get("/v1/bsm/accounts?limit=0", headers=auth("ana"))
    ).status_code == 400
    assert (
        await harness.client.get("/v1/bsm/accounts?limit=201", headers=auth("ana"))
    ).status_code == 400


# ---------------------------------------------------------------------- alterar e remover


async def test_update_publishes_with_the_resource_version(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana")
    response = await harness.client.patch(
        "/v1/bsm/accounts/ba-1",
        json={
            "resourceVersion": "3",
            "displayName": "Novo Nome",
            "billingContacts": ["novo@acme.example"],
        },
        headers=auth("ana"),
    )
    assert response.status_code == 202
    subject, payload, _ = harness.publisher.published[0]
    assert subject == "receiver.requested.bsm.account.ba-1.update"
    assert payload["data"]["resourceVersion"] == "3"
    assert payload["data"]["specification"] == {
        "displayName": "Novo Nome",
        "billingContacts": ["novo@acme.example"],
    }


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"resourceVersion": "2", "displayName": "Novo"}, 409),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, 403),
        ({"resourceVersion": "3"}, 400),
        ({"resourceVersion": "abc", "displayName": "Novo"}, 400),
        ({"resourceVersion": "3", "billingCurrency": "USD"}, 400),
        (
            {
                "resourceVersion": "3",
                "billingContacts": ["finops@acme.example", "finops@acme.example"],
            },
            400,
        ),
    ],
)
async def test_update_rules(harness: Harness, body: dict[str, Any], status: int) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana")
    response = await harness.client.patch("/v1/bsm/accounts/ba-1", json=body, headers=auth("ana"))
    assert response.status_code == status
    assert harness.publisher.published == []


async def test_operator_may_change_reconciliation(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana")
    response = await harness.client.patch(
        "/v1/bsm/accounts/ba-1",
        json={"resourceVersion": "3", "reconciliation": "suspended"},
        headers=auth("admin"),
    )
    assert response.status_code == 202
    assert harness.publisher.published[0][1]["data"]["reconciliation"] == "suspended"


async def test_delete_requires_the_version_and_the_owner(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana")
    assert (
        await harness.client.delete("/v1/bsm/accounts/ba-1", headers=auth("ana"))
    ).status_code == 400
    assert (
        await harness.client.delete("/v1/bsm/accounts/ba-1?resourceVersion=1", headers=auth("ana"))
    ).status_code == 409
    assert (
        await harness.client.delete("/v1/bsm/accounts/ba-1?resourceVersion=3", headers=auth("bia"))
    ).status_code == 404
    ok = await harness.client.delete("/v1/bsm/accounts/ba-1?resourceVersion=3", headers=auth("ana"))
    assert ok.status_code == 202
    assert harness.publisher.published[0][0] == "receiver.requested.bsm.account.ba-1.delete"


@pytest.mark.parametrize("protected", [True, None])
async def test_delete_of_a_protected_account_is_refused(
    harness: Harness, protected: bool | None
) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana", protected=protected)
    response = await harness.client.delete(
        "/v1/bsm/accounts/ba-1?resourceVersion=3", headers=auth("ana")
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "DeletionProtected"
    assert harness.publisher.published == []


async def test_owner_may_change_deletion_protection(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana", protected=True)
    response = await harness.client.patch(
        "/v1/bsm/accounts/ba-1",
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
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana", protected=None)
    harness.repository.resources["ba-2"] = account_record("ba-2", "ana", protected=False)
    first = await harness.client.get("/v1/bsm/accounts/ba-1", headers=auth("ana"))
    second = await harness.client.get("/v1/bsm/accounts/ba-2", headers=auth("ana"))
    assert first.json()["desired"]["deletionProtection"] is True
    assert second.json()["desired"]["deletionProtection"] is False


# ---------------------------------------------------------------------- Operation


async def test_operation_is_readable_only_by_the_requester_and_operators(harness: Harness) -> None:
    harness.repository.operations["op-1"] = operation("op-1", "ana")
    harness.repository.operations["op-anon"] = operation("op-anon", "anonymous")
    path = "/v1/bsm/accounts/ba-1/operations"

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
        "/v1/bsm/accounts/outra/operations/op-1", headers=auth("ana")
    )
    assert response.status_code == 404


async def test_delete_is_refused_while_organizations_are_attached(harness: Harness) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana", protected=False)
    harness.organizations.attached.add("ba-1")
    response = await harness.client.delete(
        "/v1/bsm/accounts/ba-1?resourceVersion=3", headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (409, "ResourcesAttached")
    assert harness.publisher.published == []


@pytest.mark.parametrize(
    ("retryable", "status", "code"),
    [(True, 503, "OrganizationsUnavailable"), (False, 409, "ResourcesNotVerifiable")],
)
async def test_delete_does_not_proceed_when_organizations_cannot_be_verified(
    harness: Harness, retryable: bool, status: int, code: str
) -> None:
    harness.repository.resources["ba-1"] = account_record("ba-1", "ana", protected=False)
    harness.organizations.error = OrganizationsCheckError(retryable=retryable)
    response = await harness.client.delete(
        "/v1/bsm/accounts/ba-1?resourceVersion=3", headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (status, code)
    assert harness.publisher.published == []
