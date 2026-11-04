"""Testes unitários da API HTTP de `bsm.payment` (decisões 0098 e 0100)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from bsm_payment.api.domain.errors import unauthorized
from bsm_payment.api.domain.payment import OwnerQuota, UniqueValue
from bsm_payment.api.domain.principal import Principal
from bsm_payment.api.domain.records import ResourceRecord
from bsm_payment.api.http.app import Dependencies, create_app
from bsm_payment.api.settings import PaymentApiSettings
from bsm_payment.common.contracts import generated

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER_PERMISSIONS = frozenset(
    {
        "bsm.payment.create",
        "bsm.payment.get",
        "bsm.payment.list",
        "bsm.payment.update",
        "bsm.payment.delete",
    }
)
OPERATOR_PERMISSIONS = USER_PERMISSIONS | {"bsm.payment.operate"}


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    "ana": principal("ana", USER_PERMISSIONS),
    "bia": principal("bia", USER_PERMISSIONS),
    "admin": principal("admin", OPERATOR_PERMISSIONS),
    "norole": principal("norole", frozenset()),
}


class FakeAuthenticator:
    async def verify(self, token: str) -> Principal:
        try:
            return PRINCIPALS[token]
        except KeyError:
            raise unauthorized() from None


class FakeEmailVerifier:
    def __init__(self, verified: set[str] | None = None) -> None:
        self.verified: set[str] = verified if verified is not None else {"ana", "bia"}

    async def is_verified(self, principal: Principal) -> bool:
        return principal.subject in self.verified


class FakeBillingAccounts:
    def __init__(self) -> None:
        self.attached: set[str] = set()

    def has_attached_billing_accounts(self, payment_id: str) -> bool:
        return payment_id in self.attached


class FakeRepository:
    def __init__(self) -> None:
        self.resources: dict[str, ResourceRecord] = {}

    async def get_payment(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def list_payments(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        items = [r for r in items if owner is None or r.desired.get("ownerAccountId") == owner]
        return [r for r in items if after is None or r.resource_id > after][:limit]


class FakeAdmissionTransaction:
    """Transação em memória para os testes de admissão (decisão 0098)."""

    def __init__(self, store: FakeAdmissionStore) -> None:
        self._store = store

    @property
    def _resources(self) -> dict[str, ResourceRecord]:
        return self._store.repository.resources

    async def lock_idempotency(self, requested_by: str, key: str) -> None:
        return

    async def find_idempotency(self, requested_by: str, key: str) -> tuple[str, str] | None:
        return self._store.idempotency.get((requested_by, key))

    async def record_idempotency(
        self, requested_by: str, key: str, *, request_digest: str, resource_id: str
    ) -> None:
        self._store.idempotency[(requested_by, key)] = (request_digest, resource_id)

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool:
        return any(
            record.desired.get(unique.field) == unique.value
            and record.desired.get(unique.scope_field) == unique.scope_value
            for record in self._resources.values()
            if record.resource_id != excluding_resource_id and record.lifecycle == "present"
        )

    async def owned_count(self, quota: OwnerQuota) -> int:
        return sum(
            1
            for r in self._resources.values()
            if r.desired.get(quota.field) == quota.owner and r.lifecycle == "present"
        )

    async def insert_resource(
        self,
        resource_id: str,
        *,
        schema_version: str,
        desired: Any,
        requested_by: str,
        correlation_id: str,
    ) -> None:
        self._resources[resource_id] = ResourceRecord(
            resource_id=resource_id,
            resource_version=1,
            desired_generation=1,
            observed_generation=None,
            lifecycle=desired["lifecycle"],
            reconciliation="active",
            phase="Pending",
            conditions=[],
            desired=dict(desired),
            presence=None,
            observed=None,
            observed_at=None,
            created_at=NOW,
            updated_at=NOW,
        )

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        record = self._resources.get(resource_id)
        if record is None:
            return None
        return {
            "resource_version": record.resource_version,
            "desired_generation": record.desired_generation,
            "observed_generation": record.observed_generation,
            "lifecycle": record.lifecycle,
            "reconciliation": record.reconciliation,
            "desired": dict(record.desired),
            "phase": record.phase,
        }

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Any,
        reconciliation: str,
        phase: str,
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None:
        record = self._resources[resource_id]
        if record.resource_version != expected_resource_version:
            return None
        generation = record.desired_generation + (1 if dict(desired) != record.desired else 0)
        self._resources[resource_id] = replace(
            record,
            lifecycle=desired["lifecycle"],
            reconciliation=reconciliation,
            desired=dict(desired),
            desired_generation=generation,
            phase=phase,
            resource_version=record.resource_version + 1,
        )
        return generation

    async def add_to_outbox(self, message: Any, *, resource_id: str, subject: str) -> None:
        self._store.outbox.append((subject, dict(message), message["messageId"]))

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None:
        return self._resources.get(resource_id)


class FakeAdmissionStore:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self.outbox: list[tuple[str, dict[str, Any], str]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[FakeAdmissionTransaction]:
        yield FakeAdmissionTransaction(self)


def payment_record(
    resource_id: str,
    owner: str,
    *,
    display_name: str = "Visa Corporativo Final 4242",
    provider: str = "mercadopago",
    method_type: str = "credit_card",
    version: int = 3,
    protected: bool | None = False,
) -> ResourceRecord:
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "customerAccountId": owner,
        "displayName": display_name,
        "provider": provider,
        "methodType": method_type,
        "providerToken": "tok_test_apro_4242",
        "ownerAccountId": owner,
    }
    if protected is not None:
        desired["deletionProtection"] = protected
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        observed_generation=1,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=desired,
        presence="present",
        observed={
            "customerAccountId": owner,
            "displayName": display_name,
            "provider": provider,
            "methodType": method_type,
            "status": "active",
            "providerCustomerId": f"mp-cust-{owner}",
            "providerPaymentMethodId": f"mp-pm-{resource_id}",
            "brand": "visa",
            "lastFourDigits": "4242",
            "expirationMonth": 12,
            "expirationYear": 2030,
            "deletionProtection": protected is not False,
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class Harness:
    client: httpx.AsyncClient
    repository: FakeRepository
    store: FakeAdmissionStore
    emails: FakeEmailVerifier
    billing_accounts: FakeBillingAccounts
    settings: PaymentApiSettings


@pytest.fixture
def harness() -> Harness:
    seq = 0

    def next_id() -> str:
        nonlocal seq
        seq += 1
        return f"pm-{seq:04d}"

    settings = PaymentApiSettings()
    repository = FakeRepository()
    store = FakeAdmissionStore(repository)
    emails = FakeEmailVerifier()
    billing_accounts = FakeBillingAccounts()
    deps = Dependencies(
        settings=settings,
        authenticator=FakeAuthenticator(),
        email_verifier=emails,
        repository=repository,
        store=store,
        billing_accounts=billing_accounts,
        identifiers=next_id,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(
        client,
        repository,
        store,
        emails,
        billing_accounts,
        settings,
    )


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


CREATE_PAYLOAD: dict[str, Any] = {
    "customerAccountId": "ana",
    "displayName": "Visa Corporativo Final 4242",
    "provider": "mercadopago",
    "methodType": "credit_card",
    "providerToken": "tok_test_apro_4242",
}


async def test_health_probes_are_public_and_readiness_reflects_the_dependencies(
    harness: Harness,
) -> None:
    for probe in ("live", "startup", "ready"):
        response = await harness.client.get(f"/health/{probe}")
        assert response.status_code == 200
        assert response.json()["status"] == "UP"


async def test_readiness_is_down_when_a_critical_dependency_is_down() -> None:
    settings = PaymentApiSettings()
    repository = FakeRepository()
    deps = Dependencies(
        settings=settings,
        authenticator=FakeAuthenticator(),
        email_verifier=FakeEmailVerifier(),
        repository=repository,
        store=FakeAdmissionStore(repository),
        billing_accounts=FakeBillingAccounts(),
        is_synced=lambda: False,
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
    response = await harness.client.get("/v1/bsm/payments", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())
    assert response.json()["errorCode"] == "Unauthorized"


async def test_missing_role_is_403(harness: Harness) -> None:
    response = await harness.client.post(
        "/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("norole")
    )
    assert response.status_code == 403
    assert harness.store.outbox == []


async def test_create_admit_and_answers_201_without_exposing_provider_token(
    harness: Harness,
) -> None:
    response = await harness.client.post(
        "/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("ana")
    )

    assert response.status_code == 201
    body = generated.Payment.model_validate(response.json())
    assert (body.resource_id, body.resource_version, body.phase.value) == (
        "pm-0001",
        "1",
        "Pending",
    )
    assert body.desired.display_name == "Visa Corporativo Final 4242"
    assert "ownerAccountId" not in response.text
    assert "providerToken" not in response.text

    ((subject, payload, message_id),) = harness.store.outbox
    assert subject == "desired.bsm.payment.pm-0001"
    envelope = generated.MessageEnvelope.model_validate(payload)
    assert envelope.message_id == message_id
    assert (envelope.emitter.value, envelope.message_type.value) == ("api", "desired")
    assert envelope.requested_by == "ana"
    assert envelope.data["displayName"] == "Visa Corporativo Final 4242"
    assert envelope.data["providerToken"] == "tok_test_apro_4242"


async def test_operator_creates_without_verified_email(harness: Harness) -> None:
    harness.emails.verified.clear()
    response = await harness.client.post(
        "/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("admin")
    )
    assert response.status_code == 201


async def test_unverified_email_is_403(harness: Harness) -> None:
    harness.emails.verified.clear()
    response = await harness.client.post(
        "/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("ana")
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "EmailNotVerified")
    assert harness.store.outbox == []


async def test_customer_account_id_mismatch_is_forbidden_for_non_operators(
    harness: Harness,
) -> None:
    response = await harness.client.post(
        "/v1/bsm/payments",
        json={**CREATE_PAYLOAD, "customerAccountId": "bia"},
        headers=auth("ana"),
    )
    assert (response.status_code, response.json()["errorCode"]) == (403, "Forbidden")
    assert harness.store.outbox == []


async def test_duplicate_display_name_by_same_owner_is_409(harness: Harness) -> None:
    first = await harness.client.post("/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("ana"))
    assert first.status_code == 201

    second = await harness.client.post("/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("ana"))
    assert (second.status_code, second.json()["errorCode"]) == (409, "DisplayNameInUse")

    other = await harness.client.post(
        "/v1/bsm/payments",
        json={**CREATE_PAYLOAD, "customerAccountId": "bia"},
        headers=auth("bia"),
    )
    assert other.status_code == 201


async def test_quota_limit_is_enforced_for_non_operators(harness: Harness) -> None:
    harness.settings.api.payment_quota = 1
    first = await harness.client.post("/v1/bsm/payments", json=CREATE_PAYLOAD, headers=auth("ana"))
    assert first.status_code == 201

    payload_2 = {**CREATE_PAYLOAD, "displayName": "Outro Cartão"}
    second = await harness.client.post("/v1/bsm/payments", json=payload_2, headers=auth("ana"))
    assert (second.status_code, second.json()["errorCode"]) == (403, "QuotaExceeded")


async def test_repeating_the_same_request_returns_the_existing_resource_without_duplicate_publish(
    harness: Harness,
) -> None:
    headers = {**auth("ana"), "Idempotency-Key": "k-1"}
    first = await harness.client.post("/v1/bsm/payments", json=CREATE_PAYLOAD, headers=headers)
    assert first.status_code == 201
    assert len(harness.store.outbox) == 1

    second = await harness.client.post("/v1/bsm/payments", json=CREATE_PAYLOAD, headers=headers)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert len(harness.store.outbox) == 1


async def test_same_key_with_other_content_is_422(harness: Harness) -> None:
    headers = {**auth("ana"), "Idempotency-Key": "k-1"}
    await harness.client.post("/v1/bsm/payments", json=CREATE_PAYLOAD, headers=headers)

    other = {**CREATE_PAYLOAD, "displayName": "Outro"}
    response = await harness.client.post("/v1/bsm/payments", json=other, headers=headers)
    assert (response.status_code, response.json()["errorCode"]) == (422, "IdempotencyKeyReused")


async def test_owner_reads_the_payment_without_owner_or_token(harness: Harness) -> None:
    harness.repository.resources["pm-1"] = payment_record("pm-1", "ana")
    response = await harness.client.get("/v1/bsm/payments/pm-1", headers=auth("ana"))
    assert response.status_code == 200
    view = generated.Payment.model_validate(response.json())
    assert (view.resource_id, view.resource_version, view.phase.value) == ("pm-1", "3", "Ready")
    assert "ownerAccountId" not in response.text
    assert "providerToken" not in response.text
    assert view.observed is not None
    assert view.observed.brand == "visa"
    assert view.observed.last_four_digits == "4242"


async def test_other_users_payment_is_404_and_operator_can_read(harness: Harness) -> None:
    harness.repository.resources["pm-1"] = payment_record("pm-1", "ana")
    assert (
        await harness.client.get("/v1/bsm/payments/pm-1", headers=auth("bia"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/bsm/payments/ghost", headers=auth("ana"))
    ).status_code == 404
    assert (
        await harness.client.get("/v1/bsm/payments/pm-1", headers=auth("admin"))
    ).status_code == 200


async def test_list_is_scoped_to_the_owner_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[f"p-{index}"] = payment_record(f"p-{index}", "ana")
    harness.repository.resources["b-0"] = payment_record("b-0", "bia")

    first = (await harness.client.get("/v1/bsm/payments?limit=2", headers=auth("ana"))).json()
    assert [item["resourceId"] for item in first["items"]] == ["p-0", "p-1"]
    second = (
        await harness.client.get(
            f"/v1/bsm/payments?limit=2&cursor={first['nextCursor']}", headers=auth("ana")
        )
    ).json()
    assert [item["resourceId"] for item in second["items"]] == ["p-2"]
    assert "nextCursor" not in second

    everything = (await harness.client.get("/v1/bsm/payments", headers=auth("admin"))).json()
    assert len(everything["items"]) == 4


async def test_update_modifies_record_and_publishes_desired(harness: Harness) -> None:
    harness.repository.resources["pm-1"] = payment_record("pm-1", "ana")
    response = await harness.client.patch(
        "/v1/bsm/payments/pm-1",
        json={"resourceVersion": "3", "displayName": "Novo Nome"},
        headers=auth("ana"),
    )
    assert response.status_code == 200
    assert response.json()["desired"]["displayName"] == "Novo Nome"
    assert response.json()["phase"] == "Reconciling"
    subject, payload, _ = harness.store.outbox[0]
    assert subject == "desired.bsm.payment.pm-1"
    assert payload["data"]["displayName"] == "Novo Nome"


async def test_delete_marks_deleting_and_publishes_absent_desired(harness: Harness) -> None:
    harness.repository.resources["pm-1"] = payment_record("pm-1", "ana", protected=False)
    ok = await harness.client.delete("/v1/bsm/payments/pm-1?resourceVersion=3", headers=auth("ana"))
    assert ok.status_code == 202
    assert ok.json()["phase"] == "Deleting"
    assert ok.json()["desired"]["lifecycle"] == "absent"
    assert "pm-1" in harness.repository.resources
    assert harness.store.outbox[0][0] == "desired.bsm.payment.pm-1"
    assert harness.store.outbox[0][1]["data"]["lifecycle"] == "absent"


async def test_delete_of_protected_or_attached_payment_is_refused(harness: Harness) -> None:
    harness.repository.resources["pm-1"] = payment_record("pm-1", "ana", protected=True)
    protected_res = await harness.client.delete(
        "/v1/bsm/payments/pm-1?resourceVersion=3", headers=auth("ana")
    )
    assert (protected_res.status_code, protected_res.json()["errorCode"]) == (
        409,
        "DeletionProtected",
    )

    harness.repository.resources["pm-1"] = payment_record("pm-1", "ana", protected=False)
    harness.billing_accounts.attached.add("pm-1")
    attached_res = await harness.client.delete(
        "/v1/bsm/payments/pm-1?resourceVersion=3", headers=auth("ana")
    )
    assert (attached_res.status_code, attached_res.json()["errorCode"]) == (
        409,
        "ResourcesAttached",
    )
