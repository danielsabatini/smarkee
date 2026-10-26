"""Testes unitários da API HTTP do Receiver de `ipm.group` (decisão 0088)."""

from datetime import UTC, datetime
from typing import Any

import httpx

from ipm_group.receiver.domain.access import OrganizationAccess
from ipm_group.receiver.domain.errors import unauthorized
from ipm_group.receiver.domain.principal import (
    GROUP_ADMIN,
    GROUP_BIND,
    GROUP_CREATE,
    GROUP_DELETE,
    GROUP_GET,
    GROUP_LIST,
    GROUP_UPDATE,
    Principal,
)
from ipm_group.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_group.receiver.http.app import Dependencies, create_app
from ipm_group.receiver.settings import ApiSettings

FIXED_NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
ORG_ID = "01950000-0000-7000-8000-0000000000aa"


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
        self.operations: dict[str, OperationRecord] = {}

    async def get_group(self, resource_id: str) -> ResourceRecord | None:
        return self.groups.get(resource_id)

    async def list_groups(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        items = sorted(
            (
                r
                for r in self.groups.values()
                if r.desired.get("organizationId") == organization_id
            ),
            key=lambda r: r.resource_id,
        )
        if after:
            items = [r for r in items if r.resource_id > after]
        return items[:limit]

    async def count_groups_in(self, organization_id: str) -> int:
        return sum(
            1
            for r in self.groups.values()
            if r.desired.get("organizationId") == organization_id
        )

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        return self.operations.get(operation_id)


class FakeOrganizations:
    def __init__(self) -> None:
        self.owned_by_token: set[tuple[str, str]] = {("owner-token", ORG_ID)}

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess:
        if (access_token, organization_id) in self.owned_by_token:
            return OrganizationAccess.OWNED
        return OrganizationAccess.NOT_OWNED


class FakeUsers:
    def __init__(self) -> None:
        self.member_org_by_subject: dict[str, str] = {
            "member-no-bind": ORG_ID,
            "member-with-bind": ORG_ID,
        }
        self.attached_counts: dict[tuple[str, str], int] = {}

    async def count_users_with_group(
        self, organization_id: str, group_name: str, access_token: str
    ) -> int:
        _ = access_token
        return self.attached_counts.get((organization_id, group_name), 0)

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None:
        _ = access_token
        return self.member_org_by_subject.get(user_id)


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, str | None]] = []

    async def publish(self, subject: str, payload: bytes, *, message_id: str | None = None) -> None:
        self.published.append((subject, payload, message_id))


def _record(
    resource_id: str = "01950000-0000-7000-8000-000000000010",
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
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=desired,
        presence="present",
        observed={
            "name": name,
            "description": "Auditores da Organization.",
            "roles": assigned,
            "deletionProtection": deletion_protection,
        },
        observed_at=FIXED_NOW,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def _setup(
    *, quota: int = 100
) -> tuple[httpx.AsyncClient, FakeRepository, FakeUsers, FakePublisher]:
    repo = FakeRepository()
    users = FakeUsers()
    pub = FakePublisher()
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
            publisher=pub,
            clock=lambda: FIXED_NOW,
            identifiers=next_id,
        )
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, repo, users, pub


async def test_create_group_enforces_scope_catalog_bind_and_quota() -> None:
    client, _, _, pub = _setup(quota=1)
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
        assert accepted.status_code == 202
        assert len(pub.published) == 1


async def test_get_list_and_update_group() -> None:
    client, repo, _, pub = _setup()
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
        assert update_res.status_code == 202
        assert len(pub.published) == 1


async def test_delete_group_checks_protection_and_attached_users() -> None:
    client, repo, users, pub = _setup()
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
        assert pub.published == []

        users.attached_counts[(ORG_ID, "auditors")] = 0
        deleted = await client.delete(
            f"/v1/ipm/groups/{group_id}?resourceVersion=1",
            headers={"Authorization": "Bearer owner-token"},
        )
        assert deleted.status_code == 202
        assert len(pub.published) == 1
