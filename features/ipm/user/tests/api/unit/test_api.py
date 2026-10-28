"""API de usuário: escopo, `bind`, catálogo, admissão síncrona, cota e contratos."""

import itertools
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ipm_user.api.domain.access import OrganizationAccess
from ipm_user.api.domain.errors import unauthorized, unavailable
from ipm_user.api.domain.principal import Principal
from ipm_user.api.domain.records import ResourceRecord
from ipm_user.api.domain.user import OwnerQuota, UniqueValue
from ipm_user.api.http.app import Dependencies, create_app
from ipm_user.api.settings import ApiSettings
from ipm_user.common.catalog import AccessCatalog
from ipm_user.common.contracts import generated

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ORG = "org-1"
OTHER_ORG = "org-2"
USER_PERMISSIONS = frozenset(
    {"ipm.user.create", "ipm.user.get", "ipm.user.list", "ipm.user.update", "ipm.user.delete"}
)
ROOT_PERMISSIONS = USER_PERMISSIONS | {"ipm.user.bind", "ipm.organization.get"}


def principal(subject: str, permissions: frozenset[str]) -> Principal:
    return Principal(subject=subject, permissions=permissions, access_token=f"token-{subject}")


PRINCIPALS = {
    # Dono da `org-1` (confirmado pelo Receiver da Organization).
    "root": principal("root", ROOT_PERMISSIONS),
    # Usuários da `org-1` (registro próprio no SSOT): sem e com `bind`.
    "bia": principal("bia", USER_PERMISSIONS),
    "binder": principal("binder", USER_PERMISSIONS | {"ipm.user.bind"}),
    # Usuária da `org-2`.
    "eve": principal("eve", USER_PERMISSIONS | {"ipm.user.bind"}),
    "admin": principal("admin", USER_PERMISSIONS | {"ipm.user.admin"}),
    "norole": principal("norole", frozenset()),
    # Identidade de máquina da `org-1` (reconhecida pela API de ServiceAccount; 0094).
    "machine": principal("machine", USER_PERMISSIONS),
}


class FakeAuthenticator:
    async def verify(self, token: str) -> Principal:
        try:
            return PRINCIPALS[token]
        except KeyError:
            raise unauthorized() from None


def user(
    resource_id: str,
    organization_id: str = ORG,
    *,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
    groups: list[str] | None = None,
    email: str | None = None,
    version: int = 3,
    lifecycle: str = "present",
    protected: bool = False,
) -> ResourceRecord:
    effective = permissions if permissions is not None else ["ipm.user.get", "ipm.user.list"]
    desired: dict[str, Any] = {
        "lifecycle": lifecycle,
        "organizationId": organization_id,
        "roles": roles if roles is not None else ["ipm.userViewer"],
        "groups": groups if groups is not None else [],
        "deletionProtection": protected,
    }
    if lifecycle == "present":
        desired |= {
            "givenName": "Ana",
            "familyName": "Silva",
            "email": email or f"{resource_id}@example.com",
        }
    return ResourceRecord(
        resource_id=resource_id,
        resource_version=version,
        desired_generation=1,
        observed_generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=desired,
        presence="present",
        observed={
            "permissions": effective,
            "effectivePermissions": effective,
            "userState": "active",
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeRepository:
    resources: dict[str, ResourceRecord] = field(default_factory=lambda: {})

    async def get_user(self, resource_id: str) -> ResourceRecord | None:
        return self.resources.get(resource_id)

    async def list_users(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(self.resources.values(), key=lambda r: r.resource_id)
        items = [r for r in items if r.desired.get("organizationId") == organization_id]
        return [r for r in items if after is None or r.resource_id > after][:limit]


@dataclass
class FakeOrganizations:
    """Projeção local das Organizations: o dono (`subject`) de cada uma."""

    owners: dict[str, str] = field(default_factory=lambda: {ORG: "root"})
    calls: list[str] = field(default_factory=lambda: [])

    def access(self, organization_id: str, subject: str) -> OrganizationAccess:
        self.calls.append(organization_id)
        if self.owners.get(organization_id) == subject:
            return OrganizationAccess.OWNED
        return OrganizationAccess.NOT_OWNED


@dataclass
class FakeMembers:
    """Projeção local do pertencimento: a Organization de cada service account, pelo `subject`."""

    machines: dict[str, str] = field(default_factory=lambda: {"machine": ORG})
    calls: list[str] = field(default_factory=lambda: [])

    def organization_of(self, subject: str) -> str | None:
        self.calls.append(subject)
        return self.machines.get(subject)


class FakeAdmissionTransaction:
    """Transação em memória sobre o `FakeRepository` (decisão 0098), com o contrato do SSOT."""

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
    """Admissão em memória: a transação desfaz tudo se falhar, como a do banco."""

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
class Harness:
    client: httpx.AsyncClient
    admissions: FakeAdmissionStore
    repository: FakeRepository
    organizations: FakeOrganizations
    members: FakeMembers
    catalog: AccessCatalog


def dependencies(
    repository: FakeRepository,
    organizations: FakeOrganizations,
    admissions: FakeAdmissionStore | None = None,
    members: FakeMembers | None = None,
    catalog: AccessCatalog | None = None,
    **overrides: Any,
) -> Dependencies:
    counter = itertools.count(1)
    return Dependencies(
        settings=ApiSettings(user_quota=5),
        authenticator=FakeAuthenticator(),
        repository=repository,
        organizations=organizations,
        members=members if members is not None else FakeMembers(),
        admissions=admissions if admissions is not None else FakeAdmissionStore(repository),
        catalog=catalog if catalog is not None else AccessCatalog(),
        clock=lambda: NOW,
        identifiers=lambda: f"id-{next(counter):04d}",
        **overrides,
    )


@pytest.fixture
def harness() -> Harness:
    repository, organizations = FakeRepository(), FakeOrganizations()
    admissions = FakeAdmissionStore(repository)
    members = FakeMembers()
    catalog = AccessCatalog()
    catalog.apply_group_desired(
        "grp-1",
        {
            "lifecycle": "present",
            "organizationId": ORG,
            "name": "devs",
            "roles": ["ipm.userViewer"],
        },
    )
    repository.resources |= {
        "bia": user("bia", permissions=sorted(USER_PERMISSIONS)),
        "binder": user("binder"),
        "eve": user("eve", OTHER_ORG),
    }
    deps = dependencies(repository, organizations, admissions, members, catalog)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    return Harness(client, admissions, repository, organizations, members, catalog)


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {subject}"}


def body(**fields: Any) -> dict[str, Any]:
    return {
        "organizationId": ORG,
        "givenName": "Ana",
        "familyName": "Silva",
        "email": "ana@example.com",
        **fields,
    }


async def create(harness: Harness, subject: str, **fields: Any) -> httpx.Response:
    return await harness.client.post("/v1/ipm/users", json=body(**fields), headers=auth(subject))


# ---------------------------------------------------------------------- autenticação e saúde


async def test_health_probes_are_public(harness: Harness) -> None:
    for probe in ("live", "startup", "ready"):
        response = await harness.client.get(f"/health/{probe}")
        assert (response.status_code, response.json()["status"]) == (200, "UP")


async def test_readiness_is_down_when_a_critical_dependency_is_down() -> None:
    deps = dependencies(FakeRepository(), FakeOrganizations(), is_ready=lambda: False)
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
    response = await harness.client.get(f"/v1/ipm/users?organizationId={ORG}", headers=headers)
    assert response.status_code == 401
    generated.ApiError.model_validate(response.json())


async def test_missing_permission_is_403(harness: Harness) -> None:
    response = await create(harness, "norole")
    assert response.status_code == 403
    assert harness.admissions.outbox == []


# ---------------------------------------------------------------------- criar


async def test_root_creates_a_user_and_the_desired_goes_to_the_outbox(
    harness: Harness,
) -> None:
    response = await create(
        harness, "root", roles=["ipm.userViewer"], groups=["devs"], email="Ana@Example.COM "
    )

    assert response.status_code == 201
    created = generated.User.model_validate(response.json())
    assert (created.phase.value, created.desired_generation) == ("Pending", 1)
    ((subject, payload, _),) = harness.admissions.outbox
    assert subject == f"desired.ipm.user.{created.resource_id}"
    envelope = generated.MessageEnvelope.model_validate(payload)
    assert (envelope.emitter.value, envelope.message_type.value) == ("api", "desired")
    assert (envelope.requested_by, envelope.desired_generation) == ("root", 1)
    assert envelope.data == {
        "lifecycle": "present",
        "organizationId": ORG,
        "givenName": "Ana",
        "familyName": "Silva",
        "email": "ana@example.com",
        "roles": ["ipm.userViewer"],
        "groups": ["devs"],
        "deletionProtection": False,  # no usuário nasce desprotegido (decisão 0077)
        "reconciliation": "active",
    }
    generated.UserDesiredData.model_validate(envelope.data)
    stored = harness.repository.resources[created.resource_id]
    assert (stored.resource_version, stored.observed_generation) == (1, None)
    assert harness.organizations.calls == [ORG]


async def test_a_user_of_the_organization_creates_without_asking_the_organization(
    harness: Harness,
) -> None:
    response = await create(harness, "bia")
    assert response.status_code == 201
    assert harness.organizations.calls == []  # reconhecida pelo próprio registro


async def test_operator_creates_without_quota_and_without_asking_the_organization(
    harness: Harness,
) -> None:
    for index in range(6):  # acima da cota de 5: o operador não tem cota
        response = await create(
            harness, "admin", organizationId="org-9", email=f"user-{index}@example.com"
        )
        assert response.status_code == 201
    assert harness.organizations.calls == []


@pytest.mark.parametrize("subject", ["eve", "root"])
async def test_nobody_creates_in_an_organization_where_they_do_not_act(
    harness: Harness, subject: str
) -> None:
    response = await create(harness, subject, organizationId="org-9")
    assert response.status_code == 404
    assert harness.admissions.outbox == []


async def test_a_serviceaccount_acts_as_a_member_of_its_own_organization_only(
    harness: Harness,
) -> None:
    response = await create(harness, "machine")
    assert response.status_code == 201
    assert harness.members.calls == ["machine"]
    other = await create(harness, "machine", organizationId="org-9")
    assert other.status_code == 404


async def test_a_user_being_removed_no_longer_acts_in_the_organization(
    harness: Harness,
) -> None:
    harness.repository.resources["bia"] = user("bia", lifecycle="absent")
    assert (await create(harness, "bia")).status_code == 404


async def test_roles_outside_the_grant_catalog_are_400(harness: Harness) -> None:
    response = await create(harness, "root", roles=["bsm.accountAdmin"])
    assert (response.status_code, response.json()["field"]) == (400, "roles")
    assert "bsm.accountAdmin" in response.json()["message"]
    assert harness.admissions.outbox == []


async def test_without_bind_no_roles_can_be_given(
    harness: Harness,
) -> None:
    refused_bind = await create(harness, "bia", roles=["ipm.userAdmin"])
    refused_own = await create(harness, "bia", roles=["ipm.userViewer"])
    assert (refused_bind.status_code, refused_own.status_code) == (403, 403)
    assert (await create(harness, "bia", roles=[], email="u1@example.com")).status_code == 201
    assert (
        await create(harness, "binder", roles=["ipm.organizationViewer"], email="u2@example.com")
    ).status_code == 201
    assert (
        await create(harness, "root", roles=["ipm.userAdmin"], email="u3@example.com")
    ).status_code == 201


async def test_catalog_sync_pending_returns_503(harness: Harness) -> None:
    deps = dependencies(
        harness.repository,
        harness.organizations,
        harness.admissions,
        harness.members,
        harness.catalog,
        is_catalog_synced=lambda: False,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://api"
    )
    # Criar sem roles nem groups passa
    no_roles = await client.post(
        "/v1/ipm/users", json=body(roles=[], groups=[]), headers=auth("root")
    )
    assert no_roles.status_code == 201

    # Criar com roles retorna 503 CatalogSyncPending e Retry-After: 2
    with_roles = await client.post(
        "/v1/ipm/users",
        json=body(roles=["ipm.userViewer"], email="other@example.com"),
        headers=auth("root"),
    )
    assert with_roles.status_code == 503
    assert with_roles.json()["errorCode"] == "CatalogSyncPending"
    assert with_roles.headers.get("retry-after") == "2"

    # Patch alterando roles retorna 503 CatalogSyncPending
    patch_roles = await client.patch(
        "/v1/ipm/users/binder",
        json={"resourceVersion": "3", "roles": ["ipm.userViewer"]},
        headers=auth("binder"),
    )
    assert patch_roles.status_code == 503
    assert patch_roles.json()["errorCode"] == "CatalogSyncPending"

    # Patch sem mexer em roles nem groups passa
    patch_clean = await client.patch(
        "/v1/ipm/users/binder",
        json={"resourceVersion": "3", "deletionProtection": True},
        headers=auth("binder"),
    )
    assert patch_clean.status_code == 200


async def test_without_bind_no_groups_can_be_given_and_unknown_groups_are_rejected(
    harness: Harness,
) -> None:
    unknown = await create(harness, "root", groups=["unknown-group"])
    assert unknown.status_code == 400
    assert "unknown-group" in unknown.json()["message"]
    assert unknown.json()["field"] == "groups"

    # Membro sem bind não pode atribuir grupos
    refused_group = await create(harness, "bia", groups=["devs"])
    assert refused_group.status_code == 403

    # Membro com bind ou root podem atribuir grupos existentes
    assert (
        await create(harness, "binder", groups=["devs"], email="u4@example.com")
    ).status_code == 201
    assert (
        await create(harness, "root", groups=["devs"], email="u5@example.com")
    ).status_code == 201


async def test_quota_is_checked_in_the_admission_and_nothing_is_written(
    harness: Harness,
) -> None:
    for index in range(3):  # bia, binder e mais 3: 5 na org-1
        harness.repository.resources[f"u-{index}"] = user(f"u-{index}")
    before = dict(harness.repository.resources)
    response = await create(harness, "root", email="overflow@example.com")
    assert (response.status_code, response.json()["errorCode"]) == (403, "QuotaExceeded")
    assert harness.admissions.outbox == [] and harness.repository.resources == before


async def test_an_email_already_in_use_in_the_organization_is_409(harness: Harness) -> None:
    first = await create(harness, "root", email="dup@example.com")
    assert first.status_code == 201
    again = await create(harness, "root", email="DUP@example.com")
    assert (again.status_code, again.json()["errorCode"]) == (409, "NameInUse")
    other = await create(harness, "admin", organizationId="org-9", email="dup@example.com")
    assert other.status_code == 201  # e-mail é único só dentro da Organization
    assert len(harness.admissions.outbox) == 2


@pytest.mark.parametrize(
    ("fields", "field_name"),
    [
        ({"email": "nao-eh-email"}, "email"),
        ({"roles": ["Nao Valida"]}, "roles.0"),
        ({"groups": ["Grupo Inválido!"]}, "groups.0"),
        ({"organizationId": "Org Inválida"}, "organizationId"),
    ],
)
async def test_invalid_body_is_400_and_does_not_echo_values(
    harness: Harness, fields: dict[str, Any], field_name: str
) -> None:
    response = await create(harness, "root", **fields)
    assert response.status_code == 400
    assert response.json()["field"] == field_name
    for value in fields.values():
        assert str(value) not in response.text.replace("Campo inválido", "")


async def test_storage_failure_is_a_retryable_503(harness: Harness) -> None:
    harness.admissions.fail = True
    response = await create(harness, "root")
    assert (response.status_code, response.json()["errorCode"]) == (503, "StorageUnavailable")
    assert response.headers["retry-after"] == "5"


KEY_HEADERS = {"Idempotency-Key": "k-1"}


async def test_same_key_with_same_content_returns_the_same_resource_without_writing_again(
    harness: Harness,
) -> None:
    headers = {**auth("root"), **KEY_HEADERS}
    first = await harness.client.post("/v1/ipm/users", json=body(), headers=headers)
    second = await harness.client.post("/v1/ipm/users", json=body(), headers=headers)
    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json()["resourceId"] == first.json()["resourceId"]
    assert len(harness.admissions.outbox) == 1


async def test_same_key_with_other_content_is_422(harness: Harness) -> None:
    headers = {**auth("root"), **KEY_HEADERS}
    await harness.client.post("/v1/ipm/users", json=body(), headers=headers)
    other = await harness.client.post(
        "/v1/ipm/users", json=body(email="outro@example.com"), headers=headers
    )
    assert (other.status_code, other.json()["errorCode"]) == (422, "IdempotencyKeyReused")
    assert len(harness.admissions.outbox) == 1


async def test_the_same_key_of_another_requester_is_independent(harness: Harness) -> None:
    root = await harness.client.post(
        "/v1/ipm/users", json=body(), headers={**auth("root"), **KEY_HEADERS}
    )
    admin = await harness.client.post(
        "/v1/ipm/users",
        json=body(organizationId="org-9"),
        headers={**auth("admin"), **KEY_HEADERS},
    )
    assert (root.status_code, admin.status_code) == (201, 201)
    assert len(harness.admissions.outbox) == 2


# ---------------------------------------------------------------------- ler e listar


async def test_get_is_scoped_to_the_organization(harness: Harness) -> None:
    ok = await harness.client.get("/v1/ipm/users/binder", headers=auth("bia"))
    assert ok.status_code == 200
    view = generated.User.model_validate(ok.json())
    assert (view.desired.organization_id, view.desired.deletion_protection) == (ORG, False)
    assert view.observed is not None
    assert view.observed.user_state == "active"
    assert "requestedBy" not in ok.text and "failureCount" not in ok.text
    assert (
        await harness.client.get("/v1/ipm/users/binder", headers=auth("root"))
    ).status_code == 200
    assert (
        await harness.client.get("/v1/ipm/users/binder", headers=auth("eve"))
    ).status_code == 404
    assert (await harness.client.get("/v1/ipm/users/ghost", headers=auth("bia"))).status_code == 404
    assert (await harness.client.get("/v1/ipm/users/eve", headers=auth("admin"))).status_code == 200


async def test_every_user_reads_their_own_record_without_a_permission(
    harness: Harness,
) -> None:
    PRINCIPALS["self"] = principal("self", frozenset())
    harness.repository.resources["self"] = user("self")
    try:
        response = await harness.client.get("/v1/ipm/users/self", headers=auth("self"))
        assert response.status_code == 200
        other = await harness.client.get("/v1/ipm/users/bia", headers=auth("self"))
        assert other.status_code == 403
    finally:
        del PRINCIPALS["self"]


async def test_list_is_scoped_to_one_organization_and_paginated(harness: Harness) -> None:
    for index in range(3):
        harness.repository.resources[f"a-{index}"] = user(f"a-{index}")
    first = await harness.client.get(
        f"/v1/ipm/users?organizationId={ORG}&limit=2", headers=auth("bia")
    )
    page = generated.UserList.model_validate(first.json())
    assert [item.resource_id for item in page.items] == ["a-0", "a-1"]
    assert page.next_cursor == "a-1"
    rest = await harness.client.get(
        f"/v1/ipm/users?organizationId={ORG}&cursor=a-1", headers=auth("bia")
    )
    assert [item["resourceId"] for item in rest.json()["items"]] == ["a-2", "bia", "binder"]
    other = await harness.client.get(f"/v1/ipm/users?organizationId={ORG}", headers=auth("eve"))
    assert other.status_code == 404
    missing = await harness.client.get("/v1/ipm/users", headers=auth("bia"))
    assert (missing.status_code, missing.json()["field"]) == (400, "organizationId")


# ---------------------------------------------------------------------- alterar e remover


async def test_update_publishes_roles_and_protection_with_the_version(
    harness: Harness,
) -> None:
    response = await harness.client.patch(
        "/v1/ipm/users/binder",
        json={
            "resourceVersion": "3",
            "roles": ["ipm.userAdmin"],
            "groups": ["devs"],
            "deletionProtection": True,
        },
        headers=auth("root"),
    )
    assert response.status_code == 200
    data = harness.admissions.outbox[0][1]["data"]
    assert (data["roles"], data["groups"], data["deletionProtection"]) == (
        ["ipm.userAdmin"],
        ["devs"],
        True,
    )
    assert data["email"] == "binder@example.com" and data["reconciliation"] == "active"
    generated.UserDesiredData.model_validate(data)
    updated = generated.User.model_validate(response.json())
    assert (updated.resource_version, updated.desired_generation) == ("4", 2)


async def test_without_bind_roles_cannot_be_given_or_taken(
    harness: Harness,
) -> None:
    harness.repository.resources["x"] = user("x", roles=["ipm.organizationViewer"])
    path = "/v1/ipm/users/x"
    taken = await harness.client.patch(
        path, json={"resourceVersion": "3", "roles": []}, headers=auth("bia")
    )
    given_bind = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "roles": ["ipm.organizationViewer", "ipm.userAdmin"]},
        headers=auth("bia"),
    )
    given_own = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "roles": ["ipm.organizationViewer", "ipm.userViewer"]},
        headers=auth("bia"),
    )
    assert (taken.status_code, given_bind.status_code, given_own.status_code) == (403, 403, 403)
    unchanged = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "roles": ["ipm.organizationViewer"]},
        headers=auth("bia"),
    )
    assert unchanged.status_code == 200
    allowed_with_bind = await harness.client.patch(
        path,
        json={"resourceVersion": "3", "roles": ["ipm.organizationViewer", "ipm.userViewer"]},
        headers=auth("binder"),
    )
    assert allowed_with_bind.status_code == 200


async def test_without_bind_groups_cannot_be_given_or_taken(
    harness: Harness,
) -> None:
    harness.repository.resources["x"] = user("x", groups=["devs"])
    path = "/v1/ipm/users/x"
    taken = await harness.client.patch(
        path, json={"resourceVersion": "3", "groups": []}, headers=auth("bia")
    )
    assert taken.status_code == 403
    unchanged = await harness.client.patch(
        path, json={"resourceVersion": "3", "groups": ["devs"]}, headers=auth("bia")
    )
    assert unchanged.status_code == 200
    allowed_with_bind = await harness.client.patch(
        path, json={"resourceVersion": "3", "groups": []}, headers=auth("binder")
    )
    assert allowed_with_bind.status_code == 200


@pytest.mark.parametrize(
    ("payload", "subject", "status"),
    [
        ({"resourceVersion": "2", "deletionProtection": True}, "root", 409),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, "root", 403),
        ({"resourceVersion": "3"}, "root", 400),
        ({"resourceVersion": "3", "roles": ["x.y.z"]}, "root", 400),
        ({"resourceVersion": "3", "deletionProtection": True}, "eve", 404),
        ({"resourceVersion": "3", "reconciliation": "suspended"}, "admin", 200),
    ],
)
async def test_update_rules(
    harness: Harness, payload: dict[str, Any], subject: str, status: int
) -> None:
    response = await harness.client.patch(
        "/v1/ipm/users/binder", json=payload, headers=auth(subject)
    )
    assert response.status_code == status


async def test_delete_requires_the_version_and_the_organization(harness: Harness) -> None:
    path = "/v1/ipm/users/binder"
    assert (await harness.client.delete(path, headers=auth("root"))).status_code == 400
    stale = await harness.client.delete(f"{path}?resourceVersion=2", headers=auth("root"))
    assert stale.status_code == 409
    other = await harness.client.delete(f"{path}?resourceVersion=3", headers=auth("eve"))
    assert other.status_code == 404
    deleted = await harness.client.delete(f"{path}?resourceVersion=3", headers=auth("bia"))
    assert deleted.status_code == 202
    assert generated.User.model_validate(deleted.json()).phase.value == "Deleting"
    data = harness.admissions.outbox[0][1]["data"]
    assert data["lifecycle"] == "absent"
    for name in ("givenName", "familyName", "email"):
        assert name not in data
    generated.UserDesiredData.model_validate(data)


@pytest.mark.parametrize(("protected", "status"), [(True, 409), (False, 202)])
async def test_delete_is_refused_only_while_protected(
    harness: Harness, protected: bool, status: int
) -> None:
    harness.repository.resources["x"] = user("x", protected=protected)
    response = await harness.client.delete(
        "/v1/ipm/users/x?resourceVersion=3", headers=auth("root")
    )
    assert response.status_code == status
    if status == 409:
        assert response.json()["errorCode"] == "DeletionProtected"
