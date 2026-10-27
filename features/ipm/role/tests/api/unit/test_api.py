"""Testes unitários da API HTTP de `ipm.role` (decisões 0083 e 0098)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import httpx

from ipm_role.api.domain.access import AccessCheckError, OrganizationAccess
from ipm_role.api.domain.errors import unauthorized, unavailable
from ipm_role.api.domain.principal import (
    ROLE_ADMIN,
    ROLE_BIND,
    ROLE_CREATE,
    ROLE_DELETE,
    ROLE_GET,
    ROLE_LIST,
    ROLE_UPDATE,
    Principal,
)
from ipm_role.api.domain.records import ResourceRecord
from ipm_role.api.domain.role import OwnerQuota, UniqueValue
from ipm_role.api.http.app import Dependencies, create_app
from ipm_role.api.settings import ApiSettings

FIXED_NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


class FakeAuthenticator:
    def __init__(self, tokens: dict[str, Principal]) -> None:
        self._tokens = tokens

    async def verify(self, token: str) -> Principal:
        if token not in self._tokens:
            raise unauthorized()
        return self._tokens[token]


class FakeRepository:
    def __init__(self) -> None:
        self.roles: dict[str, ResourceRecord] = {}

    async def get_role(self, resource_id: str) -> ResourceRecord | None:
        return self.roles.get(resource_id)

    async def list_roles(
        self, *, organization_id: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        owners = {"core", organization_id} if organization_id else {"core"}
        items = sorted(
            (r for r in self.roles.values() if r.desired.get("organizationId", "core") in owners),
            key=lambda r: r.resource_id,
        )
        if after:
            items = [r for r in items if r.resource_id > after]
        return items[:limit]


class FakeOrganizations:
    """Projeção local das Organizations: `owners` mapeia o `subject` à Organization dele."""

    def __init__(self) -> None:
        self.owners: dict[str, str] = {}

    def access(self, organization_id: str, subject: str) -> OrganizationAccess:
        owned = self.owners.get(subject) == organization_id
        return OrganizationAccess.OWNED if owned else OrganizationAccess.NOT_OWNED


class FakeMembers:
    """Projeção local do pertencimento: `members` mapeia o `sub` à Organization dele."""

    def __init__(self) -> None:
        self.members: dict[str, str] = {}

    def organization_of(self, subject: str) -> str | None:
        return self.members.get(subject)


class FakeRoleUsage:
    def __init__(self) -> None:
        self.in_use: set[tuple[str, str]] = set()
        self.error: AccessCheckError | None = None

    async def role_in_use(self, organization_id: str, role_name: str, access_token: str) -> bool:
        _ = access_token
        if self.error is not None:
            raise self.error
        return (organization_id, role_name) in self.in_use


class FakeAdmissionTransaction:
    """Transação em memória sobre o `FakeRepository` (decisão 0098)."""

    def __init__(self, store: FakeAdmissionStore) -> None:
        self._store = store

    @property
    def _roles(self) -> dict[str, ResourceRecord]:
        return self._store.repository.roles

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
            and record.desired.get(unique.scope_field, "core") in unique.scope_values
            for record in self._roles.values()
            if record.resource_id != excluding_resource_id and record.lifecycle == "present"
        )

    async def owned_count(self, quota: OwnerQuota) -> int:
        return sum(
            1
            for r in self._roles.values()
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
        self._roles[resource_id] = ResourceRecord(
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
        record = self._roles.get(resource_id)
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
        record = self._roles[resource_id]
        if record.resource_version != expected_resource_version:
            return None
        generation = record.desired_generation + (1 if dict(desired) != record.desired else 0)
        self._roles[resource_id] = replace(
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
        del self._roles[resource_id]

    async def add_to_outbox(self, message: Any, *, resource_id: str, subject: str) -> None:
        self._store.outbox.append((subject, dict(message), message["messageId"]))

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None:
        return self._roles.get(resource_id)


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
        saved = (dict(self.repository.roles), list(self.outbox), dict(self.idempotency))
        try:
            yield FakeAdmissionTransaction(self)
        except BaseException:
            self.repository.roles = saved[0]
            self.outbox[:] = saved[1]
            self.idempotency.clear()
            self.idempotency.update(saved[2])
            raise


def _record(
    resource_id: str = "role-ipm-user-admin",
    *,
    name: str = "ipm.userAdmin",
    permissions: list[str] | None = None,
    deletion_protection: bool = True,
    organization_id: str | None = None,
) -> ResourceRecord:
    perms = permissions or ["ipm.user.bind", "ipm.user.create", "ipm.user.get"]
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "name": name,
        "description": "Administração de usuários.",
        "permissions": perms,
        "deletionProtection": deletion_protection,
    }
    if organization_id is not None:
        desired["organizationId"] = organization_id
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
        presence="present",
        observed={
            "name": name,
            "description": "Administração de usuários.",
            "permissions": perms,
            "deletionProtection": deletion_protection,
        },
        observed_at=FIXED_NOW,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


class Harness:
    def __init__(self) -> None:
        self.repo = FakeRepository()
        self.admissions = FakeAdmissionStore(self.repo)
        self.organizations = FakeOrganizations()
        self.users = FakeMembers()
        self.usage = FakeRoleUsage()
        self.quota = 2

    def client(self) -> httpx.AsyncClient:
        auth = FakeAuthenticator(
            {
                "admin-token": Principal("operator-1", frozenset({ROLE_ADMIN}), "admin-token"),
                "viewer-token": Principal(
                    "viewer-1", frozenset({ROLE_GET, ROLE_LIST}), "viewer-token"
                ),
                "no-perm-token": Principal("user-1", frozenset(), "no-perm-token"),
                # Dono (root) de `org-acme`: o API da Organization confirma pelo token.
                "owner-token": Principal(
                    "owner-1",
                    frozenset({ROLE_CREATE, ROLE_UPDATE, ROLE_DELETE, ROLE_GET, ROLE_LIST}),
                    "owner-token",
                ),
                # Membro de `org-acme` com tudo, inclusive `bind`.
                "member-token": Principal(
                    "member-1",
                    frozenset(
                        {ROLE_CREATE, ROLE_UPDATE, ROLE_DELETE, ROLE_BIND, ROLE_GET, ROLE_LIST}
                    ),
                    "member-token",
                ),
                # Service account (identidade de máquina) de `org-acme`, com `bind`.
                "machine-token": Principal(
                    "machine-1",
                    frozenset({ROLE_CREATE, ROLE_BIND, ROLE_GET, ROLE_LIST}),
                    "machine-token",
                ),
                # Membro sem `bind`.
                "nobind-token": Principal(
                    "member-2",
                    frozenset({ROLE_CREATE, ROLE_UPDATE, ROLE_DELETE, ROLE_GET, ROLE_LIST}),
                    "nobind-token",
                ),
                # Membro de outra Organization.
                "other-token": Principal(
                    "member-3",
                    frozenset({ROLE_CREATE, ROLE_UPDATE, ROLE_DELETE, ROLE_GET, ROLE_LIST}),
                    "other-token",
                ),
            }
        )
        self.organizations.owners["owner-1"] = "org-acme"
        self.users.members["machine-1"] = "org-acme"
        self.users.members.update(
            {"member-1": "org-acme", "member-2": "org-acme", "member-3": "org-other"}
        )
        counter = 0

        def next_id() -> str:
            nonlocal counter
            counter += 1
            return f"01950000-0000-7000-8000-{counter:012d}"

        app = create_app(
            Dependencies(
                settings=ApiSettings(role_quota=self.quota),
                repository=self.repo,
                organizations=self.organizations,
                members=self.users,
                role_usage=self.usage,
                admissions=self.admissions,
                authenticator=auth,
                clock=lambda: FIXED_NOW,
                identifiers=next_id,
            )
        )
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


CREATE_BODY: dict[str, Any] = {
    "organizationId": "org-acme",
    "name": "acme.billing",
    "description": "Cobrança da Acme.",
    "permissions": ["ipm.user.list", "ipm.user.get"],
}


async def test_create_requires_the_create_permission_and_a_scope() -> None:
    harness = Harness()
    async with harness.client() as client:
        denied = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("viewer-token")
        )
        assert denied.status_code == 403
        assert harness.admissions.outbox == []

        outsider = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("other-token")
        )
        assert outsider.status_code == 404  # não revela a Organization de outro

        operator = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("admin-token")
        )
        assert operator.status_code == 201
        body = operator.json()
        assert body["phase"] == "Ready"  # a Role é só dado do SSOT (decisão 0098)
        assert body["observedGeneration"] == body["desiredGeneration"] == 1
        assert len(harness.admissions.outbox) == 1
        subject, message, _ = harness.admissions.outbox[0]
        assert subject == f"manager.desired.ipm.role.{body['resourceId']}.changed"
        assert message["emitter"] == "api"
        assert message["data"]["organizationId"] == "org-acme"


async def test_owner_and_member_with_bind_create_and_carry_the_quota() -> None:
    harness = Harness()
    async with harness.client() as client:
        owner = await client.post("/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("owner-token"))
        assert owner.status_code == 201
        member = await client.post(
            "/v1/ipm/roles",
            json={**CREATE_BODY, "name": "acme.other"},
            headers=_bearer("member-token"),
        )
        assert member.status_code == 201
    assert len(harness.admissions.outbox) == 2


async def test_member_without_bind_cannot_define_permissions() -> None:
    harness = Harness()
    async with harness.client() as client:
        denied = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("nobind-token")
        )
        assert denied.status_code == 403
    assert harness.admissions.outbox == []


async def test_a_serviceaccount_acts_in_its_own_organization_as_a_member() -> None:
    harness = Harness()
    async with harness.client() as client:
        listed = await client.get(
            "/v1/ipm/roles", params={"organizationId": "org-acme"}, headers=_bearer("machine-token")
        )
        assert listed.status_code == 200
        other = await client.get(
            "/v1/ipm/roles",
            params={"organizationId": "org-other"},
            headers=_bearer("machine-token"),
        )
        assert other.status_code == 404
        created = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("machine-token")
        )
        assert created.status_code == 201


async def test_permissions_are_capped_at_the_grantable_catalog() -> None:
    harness = Harness()
    async with harness.client() as client:
        body = {**CREATE_BODY, "permissions": ["ipm.user.get", "ipm.permission.admin"]}
        for token in ("admin-token", "owner-token"):  # o teto vale também para o operador
            refused = await client.post("/v1/ipm/roles", json=body, headers=_bearer(token))
            assert refused.status_code == 400
            assert refused.json()["field"] == "permissions"
    assert harness.admissions.outbox == []


async def test_core_organization_is_reserved_to_predefined_roles() -> None:
    harness = Harness()
    async with harness.client() as client:
        response = await client.post(
            "/v1/ipm/roles",
            json={**CREATE_BODY, "organizationId": "core"},
            headers=_bearer("admin-token"),
        )
        assert response.status_code == 400
        assert response.json()["field"] == "organizationId"


async def test_quota_blocks_the_creation_beyond_the_limit_for_non_operators() -> None:
    harness = Harness()
    for index in range(2):
        harness.repo.roles[f"role-{index}"] = _record(
            f"role-{index}", name=f"acme.r{index}", organization_id="org-acme"
        )
    async with harness.client() as client:
        refused = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("owner-token")
        )
        assert refused.status_code == 403
        assert refused.json()["errorCode"] == "QuotaExceeded"
        allowed = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("admin-token")
        )
        assert allowed.status_code == 201


async def test_reads_see_predefined_plus_own_roles_and_never_another_organizations() -> None:
    harness = Harness()
    harness.repo.roles["role-core"] = _record("role-core")
    harness.repo.roles["role-acme"] = _record(
        "role-acme", name="acme.r", organization_id="org-acme"
    )
    harness.repo.roles["role-other"] = _record(
        "role-other", name="other.r", organization_id="org-other"
    )
    async with harness.client() as client:
        listed = await client.get(
            "/v1/ipm/roles", params={"organizationId": "org-acme"}, headers=_bearer("member-token")
        )
        assert listed.status_code == 200
        assert [item["resourceId"] for item in listed.json()["items"]] == ["role-acme", "role-core"]

        foreign = await client.get(
            "/v1/ipm/roles", params={"organizationId": "org-other"}, headers=_bearer("member-token")
        )
        assert foreign.status_code == 404

        assert (
            await client.get("/v1/ipm/roles/role-core", headers=_bearer("member-token"))
        ).status_code == 200
        assert (
            await client.get("/v1/ipm/roles/role-acme", headers=_bearer("member-token"))
        ).status_code == 200
        assert (
            await client.get("/v1/ipm/roles/role-other", headers=_bearer("member-token"))
        ).status_code == 404
        assert (
            await client.get("/v1/ipm/roles/role-other", headers=_bearer("admin-token"))
        ).status_code == 200

        # Sem organizationId: só as predefinidas.
        only_core = await client.get("/v1/ipm/roles", headers=_bearer("viewer-token"))
        assert [item["resourceId"] for item in only_core.json()["items"]] == ["role-core"]
        assert only_core.json()["items"][0]["desired"]["organizationId"] == "core"


async def test_predefined_roles_are_changed_only_by_the_operator() -> None:
    harness = Harness()
    harness.repo.roles["role-core"] = _record("role-core", deletion_protection=False)
    update = {"resourceVersion": "1", "description": "Nova descrição."}
    async with harness.client() as client:
        for token in ("member-token", "owner-token"):
            patched = await client.patch(
                "/v1/ipm/roles/role-core", json=update, headers=_bearer(token)
            )
            assert patched.status_code == 403
            deleted = await client.delete(
                "/v1/ipm/roles/role-core?resourceVersion=1", headers=_bearer(token)
            )
            assert deleted.status_code == 403
        ok = await client.patch(
            "/v1/ipm/roles/role-core", json=update, headers=_bearer("admin-token")
        )
        assert ok.status_code == 200


async def test_update_checks_scope_bind_and_the_grantable_cap() -> None:
    harness = Harness()
    harness.repo.roles["role-acme"] = _record(
        "role-acme", name="acme.r", permissions=["ipm.user.get"], organization_id="org-acme"
    )
    async with harness.client() as client:
        description = {"resourceVersion": "1", "description": "Outra."}
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=description, headers=_bearer("nobind-token")
            )
        ).status_code == 200
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=description, headers=_bearer("other-token")
            )
        ).status_code == 404

        # cada escrita aplicada sobe a versão: a descrição acima levou a 2
        change = {"resourceVersion": "2", "permissions": ["ipm.user.get", "ipm.user.list"]}
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=change, headers=_bearer("nobind-token")
            )
        ).status_code == 403
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=change, headers=_bearer("member-token")
            )
        ).status_code == 200
        above = {"resourceVersion": "3", "permissions": ["ipm.permission.admin"]}
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=above, headers=_bearer("member-token")
            )
        ).status_code == 400
        stale = {"resourceVersion": "9", "description": "Outra."}
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=stale, headers=_bearer("member-token")
            )
        ).status_code == 409
        pause = {"resourceVersion": "3", "reconciliation": "suspended"}
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=pause, headers=_bearer("member-token")
            )
        ).status_code == 403


async def test_delete_respects_protection_and_refuses_roles_in_use() -> None:
    harness = Harness()
    harness.repo.roles["role-acme"] = _record(
        "role-acme", name="acme.r", organization_id="org-acme", deletion_protection=True
    )
    url = "/v1/ipm/roles/role-acme?resourceVersion=1"
    async with harness.client() as client:
        protected = await client.delete(url, headers=_bearer("member-token"))
        assert protected.status_code == 409
        assert protected.json()["errorCode"] == "DeletionProtected"

        harness.repo.roles["role-acme"] = _record(
            "role-acme", name="acme.r", organization_id="org-acme", deletion_protection=False
        )
        harness.usage.in_use.add(("org-acme", "acme.r"))
        attached = await client.delete(url, headers=_bearer("member-token"))
        assert attached.status_code == 409
        assert attached.json()["errorCode"] == "ResourcesAttached"
        assert harness.admissions.outbox == []

        harness.usage.error = AccessCheckError(retryable=True)
        unknown = await client.delete(url, headers=_bearer("member-token"))
        assert unknown.status_code == 503  # na dúvida, não exclui

        harness.usage.error = None
        harness.usage.in_use.clear()
        deleted = await client.delete(url, headers=_bearer("member-token"))
        assert deleted.status_code == 202
        assert deleted.json()["phase"] == "Deleting"
        assert "role-acme" not in harness.repo.roles  # a linha sai do SSOT
        message = harness.admissions.outbox[0][1]
        assert message["data"]["lifecycle"] == "absent"  # o tombstone vai no outbox
        assert len(harness.admissions.outbox) == 1
