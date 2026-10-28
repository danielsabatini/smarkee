from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ipm_permission.api.domain.errors import unauthorized, unavailable
from ipm_permission.api.domain.permission import UniqueValue
from ipm_permission.api.domain.principal import Principal
from ipm_permission.api.domain.records import ResourceRecord
from ipm_permission.api.http.app import Dependencies, create_app

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
READER_PERMISSIONS = frozenset({"ipm.permission.get", "ipm.permission.list"})
OPERATOR_PERMISSIONS = READER_PERMISSIONS | {"ipm.permission.admin"}


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    "viewer": principal("viewer", READER_PERMISSIONS),
    "admin": principal("admin", OPERATOR_PERMISSIONS),
    "norole": principal("norole", frozenset()),
}


class FakeAuthenticator:
    async def verify(self, token: str) -> Principal:
        try:
            return PRINCIPALS[token]
        except KeyError:
            raise unauthorized() from None


def sample_record(
    resource_id: str = "perm-1",
    *,
    name: str = "ipm.thing.get",
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
            "description": "Ler coisas",
            "grantable": False,
            "deletionProtection": deletion_protection,
        },
        presence="present",
        observed={"name": name, "description": "Ler coisas", "group": "ipm"},
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})

    async def get_permission(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def list_permissions(self, *, after: str | None, limit: int) -> list[ResourceRecord]:
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        return [r for r in items if after is None or r.resource_id > after][:limit]


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
            if record.resource_id != excluding_resource_id and record.lifecycle == "present"
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


@pytest.fixture
def env() -> Environment:
    repo = FakeRepository()
    admissions = FakeAdmissionStore(repo)
    ids = [f"id-{n}" for n in range(1, 100)]
    deps = Dependencies(
        authenticator=FakeAuthenticator(),
        repository=repo,
        admissions=admissions,
        clock=lambda: NOW,
        identifiers=lambda: ids.pop(0),
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)),
        base_url="http://test",
    )
    return Environment(client, repo, admissions)


ADMIN = {"Authorization": "Bearer admin"}
VIEWER = {"Authorization": "Bearer viewer"}
NEW_PERMISSION = {"name": "ipm.thing.get", "description": "Ler coisas", "grantable": False}


async def test_create_permission_returns_201_and_publishes_desired(env: Environment) -> None:
    response = await env.client.post("/v1/ipm/permissions", headers=ADMIN, json=NEW_PERMISSION)
    assert response.status_code == 201
    payload = response.json()
    assert payload["resourceId"] == "id-1"
    assert payload["phase"] == "Pending"
    assert payload["desired"]["name"] == "ipm.thing.get"
    assert payload["desired"]["deletionProtection"] is True
    assert len(env.admissions.outbox) == 1
    subject, message, _ = env.admissions.outbox[0]
    assert subject == "desired.ipm.permission.id-1"
    assert message["emitter"] == "api"
    assert message["desiredGeneration"] == 1


async def test_create_requires_the_admin_permission(env: Environment) -> None:
    response = await env.client.post("/v1/ipm/permissions", headers=VIEWER, json=NEW_PERMISSION)
    assert response.status_code == 403
    assert env.admissions.outbox == []


async def test_create_without_token_is_unauthorized(env: Environment) -> None:
    response = await env.client.post("/v1/ipm/permissions", json=NEW_PERMISSION)
    assert response.status_code == 401


async def test_create_description_repeating_the_name_is_rejected(env: Environment) -> None:
    body = {**NEW_PERMISSION, "description": "ipm.thing.get"}
    response = await env.client.post("/v1/ipm/permissions", headers=ADMIN, json=body)
    assert response.status_code == 400
    assert response.json()["field"] == "description"


async def test_create_duplicate_name_is_rejected(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record(name="ipm.thing.get")
    response = await env.client.post("/v1/ipm/permissions", headers=ADMIN, json=NEW_PERMISSION)
    assert response.status_code == 409
    assert response.json()["errorCode"] == "NameInUse"


async def test_create_reuses_the_name_of_a_permission_being_removed(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record(name="ipm.thing.get", lifecycle="absent")
    response = await env.client.post("/v1/ipm/permissions", headers=ADMIN, json=NEW_PERMISSION)
    assert response.status_code == 201


async def test_create_idempotency_replay(env: Environment) -> None:
    headers = {**ADMIN, "Idempotency-Key": "req-1"}
    r1 = await env.client.post("/v1/ipm/permissions", headers=headers, json=NEW_PERMISSION)
    assert r1.status_code == 201

    r2 = await env.client.post("/v1/ipm/permissions", headers=headers, json=NEW_PERMISSION)
    assert r2.status_code == 201
    assert r2.json()["resourceId"] == r1.json()["resourceId"]
    assert len(env.admissions.outbox) == 1  # não publicou duas vezes


async def test_create_idempotency_key_reused_with_different_body(env: Environment) -> None:
    headers = {**ADMIN, "Idempotency-Key": "req-1"}
    await env.client.post("/v1/ipm/permissions", headers=headers, json=NEW_PERMISSION)

    other = {**NEW_PERMISSION, "name": "ipm.other.get"}
    r2 = await env.client.post("/v1/ipm/permissions", headers=headers, json=other)
    assert r2.status_code == 422
    assert r2.json()["errorCode"] == "IdempotencyKeyReused"


async def test_get_and_list_work_for_a_reader(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1")

    got = await env.client.get("/v1/ipm/permissions/perm-1", headers=VIEWER)
    assert got.status_code == 200
    assert got.json()["observedGeneration"] == 1

    listed = await env.client.get("/v1/ipm/permissions", headers=VIEWER)
    assert listed.status_code == 200
    assert [item["resourceId"] for item in listed.json()["items"]] == ["perm-1"]


async def test_get_without_permission_is_forbidden(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1")
    response = await env.client.get(
        "/v1/ipm/permissions/perm-1", headers={"Authorization": "Bearer norole"}
    )
    assert response.status_code == 403


async def test_get_unknown_permission_is_not_found(env: Environment) -> None:
    response = await env.client.get("/v1/ipm/permissions/missing", headers=VIEWER)
    assert response.status_code == 404


async def test_list_paginates_with_after(env: Environment) -> None:
    for number in range(3):
        env.repository.resources[f"perm-{number}"] = sample_record(f"perm-{number}")
    first = await env.client.get("/v1/ipm/permissions?limit=2", headers=VIEWER)
    assert [item["resourceId"] for item in first.json()["items"]] == ["perm-0", "perm-1"]
    cursor = first.json()["nextCursor"]
    second = await env.client.get(f"/v1/ipm/permissions?limit=2&after={cursor}", headers=VIEWER)
    assert [item["resourceId"] for item in second.json()["items"]] == ["perm-2"]
    assert "nextCursor" not in second.json()


async def test_patch_returns_200_and_updates_generation(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1", version=1)
    response = await env.client.patch(
        "/v1/ipm/permissions/perm-1",
        headers=ADMIN,
        json={"resourceVersion": "1", "description": "Ler as coisas", "grantable": True},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["desired"]["description"] == "Ler as coisas"
    assert payload["desired"]["grantable"] is True
    assert payload["desiredGeneration"] == 2
    assert payload["phase"] == "Reconciling"
    assert len(env.admissions.outbox) == 1


async def test_patch_requires_the_admin_permission(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1")
    response = await env.client.patch(
        "/v1/ipm/permissions/perm-1",
        headers=VIEWER,
        json={"resourceVersion": "1", "grantable": True},
    )
    assert response.status_code == 403


async def test_patch_conflict_when_version_diverges(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1", version=2)
    response = await env.client.patch(
        "/v1/ipm/permissions/perm-1",
        headers=ADMIN,
        json={"resourceVersion": "1", "grantable": True},
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "Conflict"


async def test_patch_without_changes_is_rejected(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1")
    response = await env.client.patch(
        "/v1/ipm/permissions/perm-1", headers=ADMIN, json={"resourceVersion": "1"}
    )
    assert response.status_code == 400


async def test_delete_returns_202_and_sets_deleting(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1", deletion_protection=False)
    response = await env.client.delete(
        "/v1/ipm/permissions/perm-1?resourceVersion=1", headers=ADMIN
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["phase"] == "Deleting"
    assert payload["desired"]["lifecycle"] == "absent"


async def test_delete_fails_if_deletion_protected(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1", deletion_protection=True)
    response = await env.client.delete(
        "/v1/ipm/permissions/perm-1?resourceVersion=1", headers=ADMIN
    )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "DeletionProtected"


async def test_delete_requires_the_admin_permission(env: Environment) -> None:
    env.repository.resources["perm-1"] = sample_record("perm-1", deletion_protection=False)
    response = await env.client.delete(
        "/v1/ipm/permissions/perm-1?resourceVersion=1", headers=VIEWER
    )
    assert response.status_code == 403


async def test_admission_failure_is_unavailable_and_publishes_nothing(env: Environment) -> None:
    env.admissions.fail = True
    response = await env.client.post("/v1/ipm/permissions", headers=ADMIN, json=NEW_PERMISSION)
    assert response.status_code == 503
    assert env.admissions.outbox == []
