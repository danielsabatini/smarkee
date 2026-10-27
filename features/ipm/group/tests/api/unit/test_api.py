"""Testes unitários da API HTTP de `ipm.group` (decisões 0088 e 0098)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import httpx

from ipm_group.api.domain.access import OrganizationAccess
from ipm_group.api.domain.errors import unauthorized, unavailable
from ipm_group.api.domain.group import OwnerQuota, UniqueValue
from ipm_group.api.domain.principal import (
    GROUP_ADMIN,
    GROUP_BIND,
    GROUP_CREATE,
    GROUP_DELETE,
    GROUP_GET,
    GROUP_LIST,
    GROUP_UPDATE,
    Principal,
)
from ipm_group.api.domain.records import ResourceRecord
from ipm_group.api.http.app import Dependencies, create_app
from ipm_group.api.settings import ApiSettings

FIXED_NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
ORG_ID = "01950000-0000-7000-8000-0000000000aa"
GROUP_ID = "01950000-0000-7000-8000-000000000010"


class FakeAuthenticator:
    def __init__(self, tokens: dict[str, Principal]) -> None:
        self._tokens = tokens

    async def verify(self, token: str) -> Principal:
        if token not in self._tokens:
            raise unauthorized()
        return self._tokens[token]


class FakeRepository:
    def __init__(self) -> None:
        self.groups: dict[str, ResourceRecord] = {}

    async def get_group(self, resource_id: str) -> ResourceRecord | None:
        return self.groups.get(resource_id)

    async def list_groups(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(
            (r for r in self.groups.values() if r.desired.get("organizationId") == organization_id),
            key=lambda r: r.resource_id,
        )
        if after:
            items = [r for r in items if r.resource_id > after]
        return items[:limit]


class FakeOrganizations:
    def __init__(self) -> None:
        self.owned_by_subject: set[tuple[str, str]] = {("owner-1", ORG_ID)}

    def access(self, organization_id: str, subject: str) -> OrganizationAccess:
        if (subject, organization_id) in self.owned_by_subject:
            return OrganizationAccess.OWNED
        return OrganizationAccess.NOT_OWNED


class FakeUsers:
    def __init__(self) -> None:
        self.attached_counts: dict[tuple[str, str], int] = {}

    def count_users_with_group(self, organization_id: str, group_name: str) -> int:
        return self.attached_counts.get((organization_id, group_name), 0)


class FakeMembers:
    """Projeção local do pertencimento: `machine-1` é uma identidade de máquina da `ORG_ID`."""

    def __init__(self) -> None:
        self.organization_by_subject: dict[str, str] = {
            "member-no-bind": ORG_ID,
            "member-with-bind": ORG_ID,
            "machine-1": ORG_ID,
        }

    def organization_of(self, subject: str) -> str | None:
        return self.organization_by_subject.get(subject)


class FakeAdmissionTransaction:
    """Transação em memória sobre o `FakeRepository` (decisão 0098)."""

    def __init__(self, store: FakeAdmissionStore) -> None:
        self._store = store

    @property
    def _groups(self) -> dict[str, ResourceRecord]:
        return self._store.repository.groups

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
            for record in self._groups.values()
            if record.resource_id != excluding_resource_id and record.lifecycle == "present"
        )

    async def owned_count(self, quota: OwnerQuota) -> int:
        return sum(
            1
            for r in self._groups.values()
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
        self._groups[resource_id] = ResourceRecord(
            resource_id=resource_id,
            resource_version=1,
            desired_generation=1,
            observed_generation=1,
            lifecycle=desired["lifecycle"],
            reconciliation="active",
            phase="Ready",
            conditions=[],
            desired=dict(desired),
            presence=None,
            observed=None,
            observed_at=None,
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        record = self._groups.get(resource_id)
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
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None:
        record = self._groups[resource_id]
        if record.resource_version != expected_resource_version:
            return None
        generation = record.desired_generation + (1 if dict(desired) != record.desired else 0)
        self._groups[resource_id] = replace(
            record,
            reconciliation=reconciliation,
            desired=dict(desired),
            desired_generation=generation,
            observed_generation=generation,
            phase="Ready",
            resource_version=record.resource_version + 1,
        )
        return generation

    async def delete_resource(self, resource_id: str) -> None:
        del self._groups[resource_id]

    async def add_to_outbox(self, message: Any, *, resource_id: str, subject: str) -> None:
        self._store.outbox.append((subject, dict(message), message["messageId"]))

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None:
        return self._groups.get(resource_id)


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
        saved = (dict(self.repository.groups), list(self.outbox), dict(self.idempotency))
        try:
            yield FakeAdmissionTransaction(self)
        except BaseException:
            self.repository.groups = saved[0]
            self.outbox[:] = saved[1]
            self.idempotency.clear()
            self.idempotency.update(saved[2])
            raise


def _record(
    resource_id: str = GROUP_ID,
    *,
    name: str = "auditors",
    roles: list[str] | None = None,
    deletion_protection: bool = False,
) -> ResourceRecord:
    assigned = roles if roles is not None else ["ipm.userViewer"]
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "organizationId": ORG_ID,
        "name": name,
        "description": "Auditores da Organization.",
        "roles": assigned,
        "deletionProtection": deletion_protection,
    }
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=1,
        desired_generation=1,
        observed_generation=1,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=desired,
        presence=None,
        observed=None,
        observed_at=None,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def _setup(
    *, quota: int = 100
) -> tuple[httpx.AsyncClient, FakeRepository, FakeUsers, FakeAdmissionStore]:
    repo = FakeRepository()
    users = FakeUsers()
    admissions = FakeAdmissionStore(repo)
    auth = FakeAuthenticator(
        {
            "admin-token": Principal(
                subject="operator-1",
                permissions=frozenset({GROUP_ADMIN}),
                access_token="admin-token",
            ),
            "owner-token": Principal(
                subject="owner-1",
                permissions=frozenset(
                    {GROUP_GET, GROUP_LIST, GROUP_CREATE, GROUP_UPDATE, GROUP_DELETE, GROUP_BIND}
                ),
                access_token="owner-token",
            ),
            "member-no-bind-token": Principal(
                subject="member-no-bind",
                permissions=frozenset({GROUP_GET, GROUP_LIST, GROUP_CREATE, GROUP_UPDATE}),
                access_token="member-no-bind-token",
            ),
            "member-bind-token": Principal(
                subject="member-with-bind",
                permissions=frozenset({GROUP_CREATE, GROUP_UPDATE, GROUP_BIND}),
                access_token="member-bind-token",
            ),
            "machine-token": Principal(
                subject="machine-1",
                permissions=frozenset({GROUP_GET, GROUP_LIST, GROUP_CREATE}),
                access_token="machine-token",
            ),
            "outsider-token": Principal(
                subject="outsider-1",
                permissions=frozenset({GROUP_GET, GROUP_LIST, GROUP_CREATE}),
                access_token="outsider-token",
            ),
        }
    )
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"01950000-0000-7000-8000-{counter:012d}"

    app = create_app(
        Dependencies(
            settings=ApiSettings(group_quota=quota),
            authenticator=auth,
            repository=repo,
            organizations=FakeOrganizations(),
            users=users,
            members=FakeMembers(),
            admissions=admissions,
            clock=lambda: FIXED_NOW,
            identifiers=next_id,
        )
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, repo, users, admissions


async def test_create_group_enforces_scope_catalog_bind_and_quota() -> None:
    client, _, _, adm = _setup(quota=1)
    async with client:
        body = {
            "organizationId": ORG_ID,
            "name": "auditors",
            "description": "Auditores da Organization.",
            "roles": ["ipm.userViewer"],
        }
        outsider = await client.post(
            "/v1/ipm/groups",
            json=body,
            headers={"Authorization": "Bearer outsider-token"},
        )
        assert outsider.status_code == 404

        no_bind = await client.post(
            "/v1/ipm/groups",
            json=body,
            headers={"Authorization": "Bearer member-no-bind-token"},
        )
        assert no_bind.status_code == 403

        bad_role = await client.post(
            "/v1/ipm/groups",
            json={**body, "roles": ["ipm.unknownViewer"]},
            headers={"Authorization": "Bearer member-bind-token"},
        )
        assert bad_role.status_code == 400
        assert bad_role.json()["field"] == "roles"

        accepted = await client.post(
            "/v1/ipm/groups",
            json=body,
            headers={"Authorization": "Bearer member-bind-token"},
        )
        assert accepted.status_code == 201
        assert accepted.json()["phase"] == "Ready"  # o Grupo é só dado do SSOT (decisão 0098)
        assert len(adm.outbox) == 1
        assert adm.outbox[0][1]["emitter"] == "api"


async def test_a_serviceaccount_acts_in_its_own_organization_as_a_member() -> None:
    client, _, _, adm = _setup()
    async with client:
        listed = await client.get(
            "/v1/ipm/groups",
            params={"organizationId": ORG_ID},
            headers={"Authorization": "Bearer machine-token"},
        )
        assert listed.status_code == 200
        elsewhere = await client.get(
            "/v1/ipm/groups",
            params={"organizationId": "org-other"},
            headers={"Authorization": "Bearer machine-token"},
        )
        assert elsewhere.status_code == 404
        # Como MEMBER sem `bind`, não atribui roles (decisão 0094).
        created = await client.post(
            "/v1/ipm/groups",
            json={
                "organizationId": ORG_ID,
                "name": "auditors",
                "description": "Auditores da Organization.",
                "roles": ["ipm.userViewer"],
            },
            headers={"Authorization": "Bearer machine-token"},
        )
        assert created.status_code == 403
        assert adm.outbox == []


async def test_get_list_and_update_group() -> None:
    client, repo, _, adm = _setup()
    group_id = "01950000-0000-7000-8000-000000000010"
    repo.groups[group_id] = _record(group_id)
    async with client:
        get_res = await client.get(
            f"/v1/ipm/groups/{group_id}",
            headers={"Authorization": "Bearer owner-token"},
        )
        assert get_res.status_code == 200
        assert get_res.json()["desired"]["name"] == "auditors"

        list_res = await client.get(
            f"/v1/ipm/groups?organizationId={ORG_ID}",
            headers={"Authorization": "Bearer owner-token"},
        )
        assert list_res.status_code == 200
        assert len(list_res.json()["items"]) == 1

        conflict_res = await client.patch(
            f"/v1/ipm/groups/{group_id}",
            json={"resourceVersion": "99", "description": "Outra."},
            headers={"Authorization": "Bearer owner-token"},
        )
        assert conflict_res.status_code == 409
        assert conflict_res.json()["errorCode"] == "Conflict"

        update_res = await client.patch(
            f"/v1/ipm/groups/{group_id}",
            json={
                "resourceVersion": "1",
                "description": "Nova descrição.",
                "roles": ["ipm.userViewer", "bsm.accountViewer"],
            },
            headers={"Authorization": "Bearer owner-token"},
        )
        assert update_res.status_code == 200
        assert len(adm.outbox) == 1


async def test_delete_group_checks_protection_and_attached_users() -> None:
    client, repo, users, adm = _setup()
    group_id = "01950000-0000-7000-8000-000000000010"
    repo.groups[group_id] = _record(group_id, deletion_protection=True)
    async with client:
        protected = await client.delete(
            f"/v1/ipm/groups/{group_id}?resourceVersion=1",
            headers={"Authorization": "Bearer owner-token"},
        )
        assert protected.status_code == 409
        assert protected.json()["errorCode"] == "DeletionProtected"

        repo.groups[group_id] = _record(group_id, deletion_protection=False)
        users.attached_counts[(ORG_ID, "auditors")] = 2
        attached = await client.delete(
            f"/v1/ipm/groups/{group_id}?resourceVersion=1",
            headers={"Authorization": "Bearer owner-token"},
        )
        assert attached.status_code == 409
        assert attached.json()["errorCode"] == "ResourcesAttached"
        assert adm.outbox == []

        users.attached_counts[(ORG_ID, "auditors")] = 0
        deleted = await client.delete(
            f"/v1/ipm/groups/{group_id}?resourceVersion=1",
            headers={"Authorization": "Bearer owner-token"},
        )
        assert deleted.status_code == 202
        assert deleted.json()["phase"] == "Deleting"
        assert group_id not in repo.groups
        subject, message, _ = adm.outbox[0]
        assert subject == f"manager.desired.ipm.group.{group_id}.changed"
        assert message["data"]["lifecycle"] == "absent"
        assert message["emitter"] == "api"


async def test_duplicate_name_in_the_organization_is_a_conflict() -> None:
    client, repo, _, adm = _setup()
    repo.groups[GROUP_ID] = _record(GROUP_ID)
    body: dict[str, Any] = {
        "organizationId": ORG_ID,
        "name": "auditors",
        "description": "Outro.",
        "roles": [],
    }
    async with client:
        response = await client.post(
            "/v1/ipm/groups", json=body, headers={"Authorization": "Bearer owner-token"}
        )
    assert response.status_code == 409
    assert adm.outbox == []


async def test_idempotency_key_replays_the_same_group() -> None:
    client, _, _, adm = _setup()
    body: dict[str, Any] = {
        "organizationId": ORG_ID,
        "name": "auditors",
        "description": "Um.",
        "roles": [],
    }
    headers = {"Authorization": "Bearer owner-token", "Idempotency-Key": "key-1"}
    async with client:
        first = await client.post("/v1/ipm/groups", json=body, headers=headers)
        second = await client.post("/v1/ipm/groups", json=body, headers=headers)
        different = await client.post(
            "/v1/ipm/groups", json={**body, "name": "other"}, headers=headers
        )
    assert first.status_code == 201
    assert second.json()["resourceId"] == first.json()["resourceId"]
    assert len(adm.outbox) == 1
    assert different.status_code == 422  # chave reutilizada com outro corpo
