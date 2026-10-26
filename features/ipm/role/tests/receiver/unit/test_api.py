"""Testes unitários da API HTTP do Receiver de `ipm.role` (decisão 0083)."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from ipm_role.receiver.domain.access import AccessCheckError, OrganizationAccess
from ipm_role.receiver.domain.errors import unauthorized
from ipm_role.receiver.domain.principal import (
    ROLE_ADMIN,
    ROLE_BIND,
    ROLE_CREATE,
    ROLE_DELETE,
    ROLE_GET,
    ROLE_LIST,
    ROLE_UPDATE,
    Principal,
)
from ipm_role.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_role.receiver.http.app import Dependencies, create_app
from ipm_role.receiver.settings import ApiSettings

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
        self.operations: dict[str, OperationRecord] = {}

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

    async def count_custom_roles_in(self, organization_id: str) -> int:
        return sum(
            1
            for r in self.roles.values()
            if r.desired.get("organizationId") == organization_id and r.lifecycle == "present"
        )

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        return self.operations.get(operation_id)


class FakeOrganizations:
    """Receiver da Organization: `owners` mapeia o token à Organization de que ele é dono."""

    def __init__(self) -> None:
        self.owners: dict[str, str] = {}
        self.error: AccessCheckError | None = None

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess:
        if self.error is not None:
            raise self.error
        owned = self.owners.get(access_token) == organization_id
        return OrganizationAccess.OWNED if owned else OrganizationAccess.NOT_OWNED


class FakeUsers:
    """Receiver de User: `members` mapeia o `sub` à Organization dele."""

    def __init__(self) -> None:
        self.members: dict[str, str] = {}

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None:
        _ = access_token
        return self.members.get(user_id)


class FakeRoleUsage:
    def __init__(self) -> None:
        self.in_use: set[tuple[str, str]] = set()
        self.error: AccessCheckError | None = None

    async def role_in_use(self, organization_id: str, role_name: str, access_token: str) -> bool:
        _ = access_token
        if self.error is not None:
            raise self.error
        return (organization_id, role_name) in self.in_use


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, str | None]] = []

    async def publish(self, subject: str, payload: bytes, *, message_id: str | None = None) -> None:
        self.published.append((subject, payload, message_id))


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
        self.pub = FakePublisher()
        self.organizations = FakeOrganizations()
        self.users = FakeUsers()
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
                # Dono (root) de `org-acme`: o Receiver da Organization confirma pelo token.
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
        self.organizations.owners["owner-token"] = "org-acme"
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
                users=self.users,
                role_usage=self.usage,
                publisher=self.pub,
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
        assert harness.pub.published == []

        outsider = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("other-token")
        )
        assert outsider.status_code == 404  # não revela a Organization de outro

        operator = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("admin-token")
        )
        assert operator.status_code == 202
        assert len(harness.pub.published) == 1
        published = json.loads(harness.pub.published[0][1])
        assert "organizationQuotaLimit" not in published["data"]  # operador não tem cota
        assert published["data"]["specification"]["organizationId"] == "org-acme"


async def test_owner_and_member_with_bind_create_and_carry_the_quota() -> None:
    harness = Harness()
    async with harness.client() as client:
        owner = await client.post("/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("owner-token"))
        assert owner.status_code == 202
        member = await client.post(
            "/v1/ipm/roles",
            json={**CREATE_BODY, "name": "acme.other"},
            headers=_bearer("member-token"),
        )
        assert member.status_code == 202
    for _, payload, _ in harness.pub.published:
        assert json.loads(payload)["data"]["organizationQuotaLimit"] == 2


async def test_member_without_bind_cannot_define_permissions() -> None:
    harness = Harness()
    async with harness.client() as client:
        denied = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("nobind-token")
        )
        assert denied.status_code == 403
    assert harness.pub.published == []


async def test_permissions_are_capped_at_the_grantable_catalog() -> None:
    harness = Harness()
    async with harness.client() as client:
        body = {**CREATE_BODY, "permissions": ["ipm.user.get", "ipm.permission.admin"]}
        for token in ("admin-token", "owner-token"):  # o teto vale também para o operador
            refused = await client.post("/v1/ipm/roles", json=body, headers=_bearer(token))
            assert refused.status_code == 400
            assert refused.json()["field"] == "permissions"
    assert harness.pub.published == []


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
        assert allowed.status_code == 202


async def test_organization_unavailable_is_a_retryable_503() -> None:
    harness = Harness()
    harness.organizations.error = AccessCheckError(retryable=True)
    async with harness.client() as client:
        response = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("no-perm-token")
        )
        assert response.status_code == 403  # sem permissão: nem chega a consultar
        harness.users.members.pop("member-1")
        unavailable = await client.post(
            "/v1/ipm/roles", json=CREATE_BODY, headers=_bearer("member-token")
        )
        assert unavailable.status_code == 503
        assert unavailable.headers["retry-after"] == "5"


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
        assert ok.status_code == 202


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
        ).status_code == 202
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=description, headers=_bearer("other-token")
            )
        ).status_code == 404

        change = {"resourceVersion": "1", "permissions": ["ipm.user.get", "ipm.user.list"]}
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=change, headers=_bearer("nobind-token")
            )
        ).status_code == 403
        assert (
            await client.patch(
                "/v1/ipm/roles/role-acme", json=change, headers=_bearer("member-token")
            )
        ).status_code == 202
        above = {"resourceVersion": "1", "permissions": ["ipm.permission.admin"]}
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
        pause = {"resourceVersion": "1", "reconciliation": "suspended"}
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
        assert harness.pub.published == []

        harness.usage.error = AccessCheckError(retryable=True)
        unknown = await client.delete(url, headers=_bearer("member-token"))
        assert unknown.status_code == 503  # na dúvida, não exclui

        harness.usage.error = None
        harness.usage.in_use.clear()
        deleted = await client.delete(url, headers=_bearer("member-token"))
        assert deleted.status_code == 202
        assert len(harness.pub.published) == 1


async def test_operation_of_a_predefined_role_is_visible_only_to_the_operator() -> None:
    harness = Harness()
    harness.repo.roles["role-core"] = _record("role-core")
    harness.repo.operations["op-1"] = OperationRecord(
        operation_id="op-1",
        resource_id="role-core",
        operation_type="update",
        desired_generation=2,
        request_digest="d" * 64,
        operation_status="accepted",
        operation_status_reason=None,
        requested_by="operator-1",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        completed_at=None,
    )
    async with harness.client() as client:
        url = "/v1/ipm/roles/role-core/operations/op-1"
        assert (await client.get(url, headers=_bearer("member-token"))).status_code == 404
        assert (await client.get(url, headers=_bearer("admin-token"))).status_code == 200


def _delete_operation(*, resource_id: str, requested_by: str) -> OperationRecord:
    return OperationRecord(
        operation_id="op-delete-1",
        resource_id=resource_id,
        operation_type="delete",
        desired_generation=3,
        request_digest="d" * 64,
        operation_status="completed",
        operation_status_reason=None,
        requested_by=requested_by,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        completed_at=FIXED_NOW,
    )


async def test_operation_of_removed_role_is_readable_by_requester_and_operators() -> None:
    """A espera de uma exclusão precisa ver o `completed` depois que a Role some (sem `404`)."""
    harness = Harness()
    role_id = "01950000-0000-7000-8000-0000000000c1"
    # A Role já foi removida: não há `ResourceRecord`, só a Operation.
    harness.repo.operations["op-delete-1"] = _delete_operation(
        resource_id=role_id, requested_by="member-1"
    )
    url = f"/v1/ipm/roles/{role_id}/operations/op-delete-1"
    async with harness.client() as client:
        requester = await client.get(url, headers=_bearer("member-token"))
        assert requester.status_code == 200
        assert requester.json()["operationStatus"] == "completed"
        assert (await client.get(url, headers=_bearer("admin-token"))).status_code == 200
        # Outra pessoa não lê a Operation de uma Role que não enxerga (nem que ela não exista).
        assert (await client.get(url, headers=_bearer("other-token"))).status_code == 404
        assert (await client.get(url, headers=_bearer("no-perm-token"))).status_code == 404
        # A Operation é do recurso da rota: com outro `role_id`, é `404` até para o solicitante.
        other = await client.get(
            "/v1/ipm/roles/01950000-0000-7000-8000-0000000000c2/operations/op-delete-1",
            headers=_bearer("member-token"),
        )
        assert other.status_code == 404
        unknown = await client.get(
            f"/v1/ipm/roles/{role_id}/operations/op-unknown", headers=_bearer("member-token")
        )
        assert unknown.status_code == 404


async def test_operation_of_an_existing_custom_role_keeps_organization_scope() -> None:
    """Quem não pediu a Operation continua lendo-a só se enxerga a Role (comportamento anterior)."""
    harness = Harness()
    role_id = "01950000-0000-7000-8000-0000000000c1"
    harness.repo.roles[role_id] = _record(role_id, name="acme.custom", organization_id="org-acme")
    harness.repo.operations["op-delete-1"] = _delete_operation(
        resource_id=role_id, requested_by="member-1"
    )
    url = f"/v1/ipm/roles/{role_id}/operations/op-delete-1"
    async with harness.client() as client:
        assert (await client.get(url, headers=_bearer("nobind-token"))).status_code == 200
        assert (await client.get(url, headers=_bearer("other-token"))).status_code == 404
