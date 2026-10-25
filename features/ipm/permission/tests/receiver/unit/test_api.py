"""Testes unitários da API HTTP do Receiver de `ipm.permission` (decisão 0083)."""

from datetime import UTC, datetime
from typing import Any

import httpx

from ipm_permission.receiver.domain.errors import unauthorized
from ipm_permission.receiver.domain.principal import (
    PERMISSION_ADMIN,
    PERMISSION_GET,
    PERMISSION_LIST,
    Principal,
)
from ipm_permission.receiver.domain.records import OperationRecord, ResourceRecord
from ipm_permission.receiver.http.app import Dependencies, create_app

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
        self.permissions: dict[str, ResourceRecord] = {}
        self.operations: dict[str, OperationRecord] = {}

    async def get_permission(self, resource_id: str) -> ResourceRecord | None:
        return self.permissions.get(resource_id)

    async def list_permissions(self, *, after: str | None, limit: int) -> list[ResourceRecord]:
        items = sorted(self.permissions.values(), key=lambda r: r.resource_id)
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
    resource_id: str = "perm-ipm-user-bind",
    *,
    name: str = "ipm.user.bind",
    grantable: bool = True,
    deletion_protection: bool = True,
) -> ResourceRecord:
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "name": name,
        "description": "Atribuir e alterar permissões de usuários da Organization.",
        "grantable": grantable,
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
            "description": "Atribuir e alterar permissões de usuários da Organization.",
            "group": "ipm",
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
                permissions=frozenset({PERMISSION_ADMIN}),
                access_token="admin-token",
            ),
            "viewer-token": Principal(
                subject="viewer-1",
                permissions=frozenset({PERMISSION_GET, PERMISSION_LIST}),
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


async def test_create_permission_requires_admin_permission() -> None:
    client, _, pub = _setup()
    async with client:
        body = {
            "name": "ipm.user.export",
            "description": "Exportar usuários da Organization.",
            "grantable": True,
        }
        forbidden_res = await client.post(
            "/v1/ipm/permissions",
            json=body,
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert forbidden_res.status_code == 403
        assert pub.published == []

        accepted_res = await client.post(
            "/v1/ipm/permissions",
            json=body,
            headers={"Authorization": "Bearer admin-token"},
        )
        assert accepted_res.status_code == 202
        assert len(pub.published) == 1


async def test_get_and_list_permissions_work_with_viewer_or_admin() -> None:
    client, repo, _ = _setup()
    repo.permissions["perm-ipm-user-bind"] = _record()
    async with client:
        get_res = await client.get(
            "/v1/ipm/permissions/perm-ipm-user-bind",
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert get_res.status_code == 200
        assert get_res.json()["desired"]["name"] == "ipm.user.bind"

        list_res = await client.get(
            "/v1/ipm/permissions",
            headers={"Authorization": "Bearer viewer-token"},
        )
        assert list_res.status_code == 200
        assert len(list_res.json()["items"]) == 1


async def test_delete_permission_respects_deletion_protection() -> None:
    client, repo, pub = _setup()
    repo.permissions["perm-ipm-user-bind"] = _record(deletion_protection=True)
    async with client:
        protected_res = await client.delete(
            "/v1/ipm/permissions/perm-ipm-user-bind?resourceVersion=1",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert protected_res.status_code == 409
        assert protected_res.json()["errorCode"] == "DeletionProtected"
        assert pub.published == []

        repo.permissions["perm-ipm-user-bind"] = _record(deletion_protection=False)
        deleted_res = await client.delete(
            "/v1/ipm/permissions/perm-ipm-user-bind?resourceVersion=1",
            headers={"Authorization": "Bearer admin-token"},
        )
        assert deleted_res.status_code == 202
        assert len(pub.published) == 1
