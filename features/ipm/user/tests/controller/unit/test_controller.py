"""Testes unitários do ciclo atômico de reconciliação do Controller (decisão 0096)."""

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
            "permissions": ["ipm.user.get"],
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
    authorizations.granted_permissions.return_value = {"ipm.user.get"}

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
    authorizations.create.assert_awaited_once_with("user-1", "org-1", ["ipm.user.get"])
    statements = [(str(query), params) for query, params in pool.conn.executed]
    update = next(p for q, p in statements if "UPDATE ipm.user SET observed" in q)
    assert "Ready" in update
    assert any("completed" in p for q, p in statements if "user_operation" in q)
    outbox = next(p for q, p in statements if "user_outbox" in q)
    assert outbox[2] == "manager.updated.ipm.user.user-1.changed"
