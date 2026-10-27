"""Testes unitários do ciclo atômico de reconciliação do Controller (decisão 0096)."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ipm_user.controller.drivers.user import IdentityUser
from ipm_user.controller.engine.controller import ControllerDrivers, UserController
from ipm_user.controller.settings import UserControllerSettings

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, row: dict[str, Any] | None, executed: list[tuple[Any, tuple[Any, ...]]]):
        self._row = row
        self._executed = executed
        self._last = ""

    async def execute(self, query: Any, params: tuple[Any, ...] = ()) -> None:
        self._last = str(query)
        self._executed.append((query, params))

    async def fetchone(self) -> dict[str, Any] | None:
        if "RETURNING resource_version" in self._last:
            return {"resource_version": 2}
        return self._row


class FakeConn:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row
        self.executed: list[tuple[Any, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        yield

    def cursor(self, *_: Any, **__: Any) -> FakeCursor:
        return FakeCursor(self._row, self.executed)

    async def execute(self, query: Any, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((query, params))


class FakePool:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.conn = FakeConn(row)

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[FakeConn]:
        yield self.conn


def present_user() -> IdentityUser:
    return IdentityUser(
        email="bia@example.com",
        organization_id="org-1",
        state="USER_STATE_ACTIVE",
        email_verified=True,
        password_set=True,
    )


@pytest.mark.asyncio
async def test_reconcile_creates_absent_user_and_saves_observation() -> None:
    row: dict[str, Any] = {
        "resource_id": "user-1",
        "desired_generation": 1,
        "observed_generation": 0,
        "resource_version": 1,
        "lifecycle": "present",
        "reconciliation": "active",
        "failure_count": 0,
        "phase": "Pending",
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "organizationId": "org-1",
            "givenName": "Bia",
            "familyName": "Lima",
            "email": "bia@example.com",
            "roles": ["ipm.userViewer"],
            "deletionProtection": False,
        },
        "observed": {},
        "presence": None,
        "requested_by": "owner-1",
        "correlation_id": "corr-1",
    }
    pool = FakePool(row)

    users: Any = AsyncMock()
    authorizations: Any = AsyncMock()
    metadata: Any = AsyncMock()
    users.get_user.side_effect = [None, present_user()]  # observação e reobservação
    users.create_user.return_value = True
    authorizations.authorization.return_value = None
    authorizations.granted_permissions.return_value = {"ipm.user.get", "ipm.user.list"}

    async def stored_metadata(_owner: str, key: str) -> str | None:
        return {"deletionProtection": "false", "groups": "[]"}.get(key)

    metadata.get_value.side_effect = stored_metadata

    controller = UserController(
        cast("Any", pool),
        ControllerDrivers(users=users, authorizations=authorizations, metadata=metadata),
        UserControllerSettings(),
        clock=lambda: NOW,
    )

    await controller.reconcile("user-1")

    users.create_user.assert_awaited_once()
    authorizations.create.assert_awaited_once_with(
        "user-1", "org-1", ["ipm.user.get", "ipm.user.list"]
    )
    statements = [(str(query), params) for query, params in pool.conn.executed]
    update = next(p for q, p in statements if "UPDATE ipm.user SET observed" in q)
    assert "Ready" in update
    outbox = next(p for q, p in statements if "user_outbox" in q)
    assert outbox[2] == "manager.updated.ipm.user.user-1.changed"


def _controller(row: dict[str, Any] | None = None) -> UserController:
    return UserController(
        cast("Any", FakePool(row)),
        ControllerDrivers(users=AsyncMock(), authorizations=AsyncMock(), metadata=AsyncMock()),
        UserControllerSettings(),
        clock=lambda: NOW,
    )


def _desired_message(resource_type: str, resource_id: str, data: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "messageId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "manager",
            "operation": "changed",
            "module": "ipm",
            "resourceType": resource_type,
            "resourceId": resource_id,
            "resourceVersion": 1,
            "desiredGeneration": 1,
            "occurredAt": NOW.isoformat(),
            "publishedAt": NOW.isoformat(),
            "data": data,
        }
    ).encode()


async def _drain(controller: UserController) -> set[str]:
    queued: set[str] = set()
    while True:
        try:
            item = await asyncio.wait_for(controller.workqueue.get(), timeout=0.05)
        except TimeoutError:
            return queued
        queued.add(item)
        controller.workqueue.done(item)


@pytest.mark.asyncio
async def test_a_role_change_requeues_only_the_users_that_have_it() -> None:
    controller = _controller()
    for user_id, roles in (("user-a", ["ipm.userViewer"]), ("user-b", ["ipm.userAdmin"])):
        await controller.on_desired_message(
            _desired_message(
                "user",
                user_id,
                {"lifecycle": "present", "organizationId": "org-1", "roles": roles},
            )
        )
    await _drain(controller)

    await controller.on_desired_message(
        _desired_message(
            "role",
            "role-1",
            {"lifecycle": "present", "name": "ipm.userViewer", "permissions": ["ipm.user.get"]},
        )
    )

    assert await _drain(controller) == {"user-a"}
    assert controller.catalog.expand_roles(["ipm.userViewer"], "org-1") == ["ipm.user.get"]


@pytest.mark.asyncio
async def test_a_group_change_requeues_its_members_only_in_that_organization() -> None:
    controller = _controller()
    for user_id, organization_id in (("user-a", "org-1"), ("user-b", "org-2")):
        await controller.on_desired_message(
            _desired_message(
                "user",
                user_id,
                {"lifecycle": "present", "organizationId": organization_id, "groups": ["devs"]},
            )
        )
    await _drain(controller)

    await controller.on_desired_message(
        _desired_message(
            "group",
            "group-1",
            {
                "lifecycle": "present",
                "organizationId": "org-1",
                "name": "devs",
                "roles": ["ipm.userViewer"],
            },
        )
    )

    assert await _drain(controller) == {"user-a"}


@pytest.mark.asyncio
async def test_an_unchanged_catalog_requeues_nobody() -> None:
    controller = _controller()
    await controller.on_desired_message(
        _desired_message(
            "user",
            "user-a",
            {"lifecycle": "present", "organizationId": "org-1", "roles": ["ipm.userViewer"]},
        )
    )
    await _drain(controller)

    await controller.on_desired_message(
        _desired_message(
            "role",
            "role-1",
            {
                "lifecycle": "present",
                "name": "ipm.userViewer",
                "permissions": controller.catalog.roles["ipm.userViewer"],
            },
        )
    )

    assert await _drain(controller) == set()


@pytest.mark.asyncio
async def test_a_removed_user_leaves_the_membership_index() -> None:
    controller = _controller()
    desired = {"lifecycle": "present", "organizationId": "org-1", "roles": ["ipm.userViewer"]}
    await controller.on_desired_message(_desired_message("user", "user-a", desired))
    assert len(controller.members) == 1

    await controller.on_desired_message(
        _desired_message("user", "user-a", {**desired, "lifecycle": "absent"})
    )

    assert len(controller.members) == 0
