from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ipm_organization.api.domain.errors import unauthorized, unavailable
from ipm_organization.api.domain.organization import OwnerQuota, UniqueValue
from ipm_organization.api.domain.principal import Principal
from ipm_organization.api.domain.records import ResourceRecord
from ipm_organization.api.http.app import Dependencies, create_app
from ipm_organization.api.settings import OrganizationApiSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER_PERMISSIONS = frozenset(
    {
        "ipm.organization.create",
        "ipm.organization.get",
        "ipm.organization.list",
        "ipm.organization.update",
        "ipm.organization.delete",
    }
)
OPERATOR_PERMISSIONS = USER_PERMISSIONS | {"ipm.organization.admin"}


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


@dataclass
class FakeEmailVerifier:
    verified: set[str] = field(default_factory=lambda: {"ana", "bia"})

    async def is_verified(self, principal: Principal) -> bool:
        return principal.subject in self.verified


@dataclass
class FakeMembers:
    members: dict[str, str] = field(default_factory=lambda: {})

    def organization_of(self, subject: str) -> str | None:
        return self.members.get(subject)


@dataclass
class FakeDependents:
    populated: set[str] = field(default_factory=lambda: set())

    def has_dependents(self, organization_id: str) -> bool:
        return organization_id in self.populated


@dataclass
class FakeBillingAccounts:
    ready_billing_accounts: set[str] = field(default_factory=lambda: {"ba-ready"})

    def is_ready_billing_account(self, billing_account_id: str, owner_account_id: str) -> bool:
        return billing_account_id in self.ready_billing_accounts


def sample_record(
    resource_id: str = "org-1",
    *,
    name: str = "acme",
    owner: str = "ana",
    version: int = 1,
    deletion_protection: bool = True,
    lifecycle: str = "present",
) -> ResourceRecord:
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        observed_generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": lifecycle,
            "name": name,
            "platformAccess": "granted",
            "deletionProtection": deletion_protection,
            "ownerAccountId": owner,
        },
        presence="present",
        observed={"name": name, "platformAccess": "granted", "organizationState": "active"},
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})

    async def get_organization(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        if owner is not None:
            items = [r for r in items if r.desired.get("ownerAccountId") == owner]
        return [r for r in items if after is None or r.resource_id > after][:limit]

    async def count_organizations_owned_by(self, owner: str) -> int:
        return sum(1 for r in self.resources.values() if r.desired.get("ownerAccountId") == owner)


class FakeAdmissionTransaction:
    """Transação em memória sobre o `FakeRepository` (decisão 0098)."""

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
            for record in self._resources.values()
            if record.resource_id != excluding_resource_id
        )

    async def owned_count(self, quota: OwnerQuota) -> int:
        return sum(1 for r in self._resources.values() if r.desired.get(quota.field) == quota.owner)

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


@dataclass
class FakeAdmissionStore:
    repository: FakeRepository
    outbox: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    idempotency: dict[tuple[str, str], tuple[str, str]] = field(default_factory=lambda: {})
    fail: bool = False

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[FakeAdmissionTransaction]:
        if self.fail:
            raise unavailable()
        saved = (dict(self.repository.resources), list(self.outbox), dict(self.idempotency))
        try:
            yield FakeAdmissionTransaction(self)
        except BaseException:
            self.repository.resources = saved[0]
            self.outbox[:] = saved[1]
            self.idempotency.clear()
            self.idempotency.update(saved[2])
            raise


@dataclass
class Environment:
    client: httpx.AsyncClient
    repository: FakeRepository
    admissions: FakeAdmissionStore
    members: FakeMembers
    dependents: FakeDependents
    billing_accounts: FakeBillingAccounts
    email: FakeEmailVerifier


@pytest.fixture
def env() -> Environment:
    repo = FakeRepository()
    admissions = FakeAdmissionStore(repo)
    members = FakeMembers()
    dependents = FakeDependents()
    billing_accounts = FakeBillingAccounts()
    email = FakeEmailVerifier()
    ids = [f"id-{n}" for n in range(1, 100)]
    deps = Dependencies(
        settings=OrganizationApiSettings(),
        authenticator=FakeAuthenticator(),
        repository=repo,
        admissions=admissions,
        members=members,
        dependents=dependents,
        billing_accounts=billing_accounts,
        email_verifier=email,
        clock=lambda: NOW,
        identifiers=lambda: ids.pop(0),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)),
        base_url="http://test",
    )
    return Environment(client, repo, admissions, members, dependents, billing_accounts, email)


async def test_create_organization_returns_201_and_publishes_desired(env: Environment) -> None:
    response = await env.client.post(
        "/v1/ipm/organizations",
        headers={"Authorization": "Bearer ana"},
        json={"name": "acme"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["resourceId"] == "id-1"
    assert payload["phase"] == "Pending"
    assert payload["desired"]["name"] == "acme"
    assert payload["desired"]["deletionProtection"] is True
    assert len(env.admissions.outbox) == 1
    subject, message, _ = env.admissions.outbox[0]
    assert subject == "manager.desired.ipm.organization.id-1.changed"
    assert message["emitter"] == "api"
    assert message["desiredGeneration"] == 1


async def test_create_reserved_name_is_rejected(env: Environment) -> None:
    response = await env.client.post(
        "/v1/ipm/organizations",
        headers={"Authorization": "Bearer ana"},
        json={"name": "smarkee"},
    )
    assert response.status_code == 422
    assert response.json()["errorCode"] == "ReservedName"


async def test_create_duplicate_name_is_rejected(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record(name="acme")
    response = await env.client.post(
        "/v1/ipm/organizations",
        headers={"Authorization": "Bearer ana"},
        json={"name": "acme"},
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "NameInUse"


async def test_create_quota_exceeded(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record(name="first", owner="ana")
    response = await env.client.post(
        "/v1/ipm/organizations",
        headers={"Authorization": "Bearer ana"},
        json={"name": "second"},
    )
    assert response.status_code == 403
    assert response.json()["errorCode"] == "QuotaExceeded"


async def test_create_email_not_verified(env: Environment) -> None:
    env.email.verified.clear()
    response = await env.client.post(
        "/v1/ipm/organizations",
        headers={"Authorization": "Bearer ana"},
        json={"name": "acme"},
    )
    assert response.status_code == 403
    assert response.json()["errorCode"] == "EmailNotVerified"


async def test_create_idempotency_replay(env: Environment) -> None:
    headers = {"Authorization": "Bearer ana", "Idempotency-Key": "req-1"}
    r1 = await env.client.post("/v1/ipm/organizations", headers=headers, json={"name": "acme"})
    assert r1.status_code == 201

    r2 = await env.client.post("/v1/ipm/organizations", headers=headers, json={"name": "acme"})
    assert r2.status_code == 201
    assert r2.json()["resourceId"] == r1.json()["resourceId"]
    assert len(env.admissions.outbox) == 1  # não publicou duas vezes


async def test_create_idempotency_key_reused_with_different_body(env: Environment) -> None:
    headers = {"Authorization": "Bearer ana", "Idempotency-Key": "req-1"}
    await env.client.post("/v1/ipm/organizations", headers=headers, json={"name": "acme"})

    r2 = await env.client.post("/v1/ipm/organizations", headers=headers, json={"name": "other"})
    assert r2.status_code == 422
    assert r2.json()["errorCode"] == "IdempotencyKeyReused"


async def test_get_organization_by_owner_and_operator(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record("org-1", owner="ana")

    r_owner = await env.client.get(
        "/v1/ipm/organizations/org-1", headers={"Authorization": "Bearer ana"}
    )
    assert r_owner.status_code == 200

    r_admin = await env.client.get(
        "/v1/ipm/organizations/org-1", headers={"Authorization": "Bearer admin"}
    )
    assert r_admin.status_code == 200

    r_other = await env.client.get(
        "/v1/ipm/organizations/org-1", headers={"Authorization": "Bearer bia"}
    )
    assert r_other.status_code == 404


async def test_patch_organization_returns_200_and_updates_generation(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record("org-1", owner="ana", version=1)
    response = await env.client.patch(
        "/v1/ipm/organizations/org-1",
        headers={"Authorization": "Bearer ana"},
        json={"resourceVersion": "1", "name": "newname"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["desired"]["name"] == "newname"
    assert payload["desiredGeneration"] == 2
    assert payload["phase"] == "Reconciling"
    assert len(env.admissions.outbox) == 1


async def test_patch_conflict_when_version_diverges(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record("org-1", owner="ana", version=2)
    response = await env.client.patch(
        "/v1/ipm/organizations/org-1",
        headers={"Authorization": "Bearer ana"},
        json={"resourceVersion": "1", "name": "newname"},
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "Conflict"


async def test_delete_organization_returns_202_and_sets_deleting(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record(
        "org-1", owner="ana", version=1, deletion_protection=False
    )
    response = await env.client.delete(
        "/v1/ipm/organizations/org-1?resourceVersion=1",
        headers={"Authorization": "Bearer ana"},
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["phase"] == "Deleting"
    assert payload["desired"]["lifecycle"] == "absent"


async def test_delete_fails_if_deletion_protected(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record(
        "org-1", owner="ana", version=1, deletion_protection=True
    )
    response = await env.client.delete(
        "/v1/ipm/organizations/org-1?resourceVersion=1",
        headers={"Authorization": "Bearer ana"},
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "DeletionProtected"


async def test_delete_fails_if_users_attached(env: Environment) -> None:
    env.repository.resources["org-1"] = sample_record(
        "org-1", owner="ana", version=1, deletion_protection=False
    )
    env.dependents.populated.add("org-1")
    response = await env.client.delete(
        "/v1/ipm/organizations/org-1?resourceVersion=1",
        headers={"Authorization": "Bearer ana"},
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "ResourcesAttached"
