"""Testes unitários da API HTTP do Receiver de `ipm.role` (decisão 0083)."""

from datetime import UTC, datetime
from typing import Any

import httpx

from ipm_role.receiver.domain.errors import unauthorized
from ipm_role.receiver.domain.principal import ROLE_ADMIN, ROLE_GET, ROLE_LIST, Principal
from ipm_role.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_role.receiver.http.app import Dependencies, create_app

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

    async def list_roles(self, *, after: str | None, limit: int) -> list[ResourceRecord]:
        items = sorted(self.roles.values(), key=lambda r: r.resource_id)
        if after:
            items = [r for r in items if r.resource_id > after]
        return items[:limit]

    async def find_operation(self, operation_id: str) -> OperationRecord | None:
        return self.operations.get(operation_id)


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
) -> ResourceRecord:
    perms = permissions or ["ipm.user.bind", "ipm.user.create", "ipm.user.get"]
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "name": name,
        "description": "Administração de usuários.",
        "permissions": perms,
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
            "description": "Administração de usuários.",
            "permissions": perms,
            "deletionProtection": deletion_protection,
        },
        observed_at=FIXED_NOW,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
    )


def _setup() -> tuple[httpx.AsyncClient, FakeRepository, FakePublisher]:
    repo = FakeRepository()
    pub = FakePublisher()
    auth = FakeAuthenticator(
        {
            "admin-token": Principal(
                subject="operator-1",
                permissions=frozenset({ROLE_ADMIN}),
                access_token="admin-token",
            ),
            "viewer-token": Principal(
                subject="viewer-1",
                permissions=frozenset({ROLE_GET, ROLE_LIST}),
                access_token="viewer-token",
            ),
            "no-perm-token": Principal(
                subject="user-1",
                permissions=frozenset(),
                access_token="no-perm-token",
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
            repository=repo,
            publisher=pub,
            authenticator=auth,
            clock=lambda: FIXED_NOW,
            identifiers=next_id,
        )
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, repo, pub


async def test_create_role_requires_admin_permission() -> None:
    client, _, pub = _setup()
    async with client:
        body = {
            "name": "ipm.userAuditor",
            "description": "Leitura de usuários.",
            "permissions": ["ipm.user.list", "ipm.user.get"],
        }
        forbidden_res = await client.post(
            "/v1/ipm/roles",
            json=body,
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert forbidden_res.status_code == 403
        assert pub.published == []

        accepted_res = await client.post(
            "/v1/ipm/roles",
            json=body,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert accepted_res.status_code == 202
        assert len(pub.published) == 1


async def test_get_and_list_roles_work_with_viewer_or_admin() -> None:
    client, repo, _ = _setup()
    repo.roles["role-ipm-user-admin"] = _record()
    async with client:
        get_res = await client.get(
            "/v1/ipm/roles/role-ipm-user-admin",
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert get_res.status_code == 200
        assert get_res.json()["desired"]["name"] == "ipm.userAdmin"

        list_res = await client.get(
            "/v1/ipm/roles",
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert list_res.status_code == 200
        assert len(list_res.json()["items"]) == 1


async def test_delete_role_respects_deletion_protection() -> None:
    client, repo, pub = _setup()
    repo.roles["role-ipm-user-admin"] = _record(deletion_protection=True)
    async with client:
        protected_res = await client.delete(
            "/v1/ipm/roles/role-ipm-user-admin?resourceVersion=1",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert protected_res.status_code == 409
        assert protected_res.json()["errorCode"] == "DeletionProtected"
        assert pub.published == []

        repo.roles["role-ipm-user-admin"] = _record(deletion_protection=False)
        deleted_res = await client.delete(
            "/v1/ipm/roles/role-ipm-user-admin?resourceVersion=1",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert deleted_res.status_code == 202
        assert len(pub.published) == 1
