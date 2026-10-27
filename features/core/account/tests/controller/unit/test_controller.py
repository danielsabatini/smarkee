"""Ciclo atômico de reconciliação do Controller de Account, sem banco (decisão 0096)."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from core_account.controller.drivers.authorization import Grant
from core_account.controller.drivers.user import IdentityUser
from core_account.controller.engine.controller import AccountController, ControllerDrivers
from core_account.controller.settings import AccountControllerSettings

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)
PERMISSIONS = ["core.account.delete", "core.account.get"]


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
        email="ana@example.com", state="USER_STATE_ACTIVE", email_verified=True, password_set=True
    )


def row_of(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "resource_id": "acc-1",
        "desired_generation": 1,
        "observed_generation": None,
        "resource_version": 1,
        "lifecycle": "present",
        "reconciliation": "active",
        "failure_count": 0,
        "phase": "Pending",
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "platformAccess": "granted",
            "platformPermissions": PERMISSIONS,
            "givenName": "Ana",
            "familyName": "Souza",
            "email": "ana@example.com",
            "deletionProtection": True,
        },
        "observed": {},
        "presence": None,
        "requested_by": "anonymous",
        "correlation_id": "corr-1",
    }
    return {**base, **changes}


def drivers() -> tuple[ControllerDrivers, Any, Any, Any]:
    users: Any = AsyncMock()
    authorizations: Any = AsyncMock()
    authorizations.project_of = MagicMock(return_value="p-core")
    metadata: Any = AsyncMock()
    return ControllerDrivers(users, authorizations, metadata), users, authorizations, metadata


def controller_of(pool: FakePool, bundle: ControllerDrivers) -> AccountController:
    return AccountController(
        cast("Any", pool), bundle, AccountControllerSettings(), clock=lambda: NOW
    )


def statements(pool: FakePool) -> list[tuple[str, tuple[Any, ...]]]:
    return [(str(query), params) for query, params in pool.conn.executed]


@pytest.mark.asyncio
async def test_reconcile_creates_the_absent_account_and_saves_the_observation() -> None:
    pool = FakePool(row_of())
    bundle, users, authorizations, metadata = drivers()
    users.get_user.side_effect = [None, present_user()]  # observação e reobservação
    users.create_user.return_value = True
    state = {"deletionProtection": "true"}

    async def read_metadata(_owner: str, key: str) -> str | None:
        return state.get(key)

    metadata.get_value.side_effect = read_metadata
    # ausente, a observação não lê autorizações; a ação não acha nenhuma; a reobservação acha
    authorizations.grants.side_effect = [[], [Grant("g-1", "p-core", frozenset(PERMISSIONS))]]

    retry = await controller_of(pool, bundle).reconcile("acc-1")

    assert retry is False
    users.create_user.assert_awaited_once()
    authorizations.create_grant.assert_awaited_once_with("acc-1", "p-core", PERMISSIONS)
    metadata.set_value.assert_awaited_once_with("acc-1", "deletionProtection", "true")
    found = statements(pool)
    update = next(p for q, p in found if "UPDATE core.account SET observed" in q)
    assert "Ready" in update
    outbox = next(p for q, p in found if "core.account_outbox" in q)
    assert outbox[2] == "manager.updated.core.account.acc-1.changed"
    assert outbox[3].obj["correlationId"] == "corr-1"


@pytest.mark.asyncio
async def test_a_reevaluation_without_news_emits_nothing() -> None:
    def converged_drivers() -> ControllerDrivers:
        bundle, users, authorizations, metadata = drivers()
        users.get_user.return_value = present_user()
        authorizations.grants.return_value = [Grant("g-1", "p-core", frozenset(PERMISSIONS))]
        metadata.get_value.return_value = "true"
        return bundle

    first = FakePool(row_of())
    await controller_of(first, converged_drivers()).reconcile("acc-1")
    update = next(p for q, p in statements(first) if "UPDATE core.account SET observed" in q)
    saved = row_of(
        phase="Ready",
        observed_generation=1,
        presence=update[1],
        observed=update[0].obj,
        conditions=update[3].obj,
    )

    again = FakePool(saved)
    bundle = converged_drivers()
    await controller_of(again, bundle).reconcile("acc-1")

    cast("Any", bundle.users).create_user.assert_not_awaited()
    assert not any("core.account_outbox" in q for q, _ in statements(again))


@pytest.mark.asyncio
async def test_reconcile_removes_the_converged_deletion_and_emits_removed() -> None:
    desired = {
        "lifecycle": "absent",
        "platformAccess": "granted",
        "platformPermissions": PERMISSIONS,
    }
    pool = FakePool(
        row_of(lifecycle="absent", desired=desired, desired_generation=3, phase="Deleting")
    )
    bundle, users, _, _ = drivers()
    users.get_user.side_effect = [present_user(), None]  # existe e, depois da ação, não existe
    cast("Any", bundle.authorizations).grants.return_value = []
    cast("Any", bundle.metadata).get_value.return_value = None

    assert await controller_of(pool, bundle).reconcile("acc-1") is False

    users.delete_user.assert_awaited_once_with("acc-1")
    found = statements(pool)
    assert any("DELETE FROM core.account" in q for q, _ in found)
    outbox = next(p for q, p in found if "core.account_outbox" in q)
    payload = outbox[3].obj
    assert (payload["data"]["removed"], payload["data"]["phase"]) == (True, "Deleting")


@pytest.mark.asyncio
async def test_a_suspended_or_missing_resource_is_left_alone() -> None:
    for row in (None, row_of(reconciliation="suspended")):
        pool = FakePool(row)
        bundle, users, _, _ = drivers()
        assert await controller_of(pool, bundle).reconcile("acc-1") is False
        users.get_user.assert_not_awaited()


def desired_message(resource_type: str, resource_id: str, module: str = "core") -> bytes:
    return json.dumps(
        {
            "messageId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "api",
            "operation": "changed",
            "module": module,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "resourceVersion": 1,
            "desiredGeneration": 1,
            "requestedBy": "anonymous",
            "correlationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4f",
            "occurredAt": NOW.isoformat(),
            "publishedAt": NOW.isoformat(),
            "data": {"lifecycle": "present"},
        }
    ).encode()


async def drain(controller: AccountController) -> set[str]:
    queued: set[str] = set()
    while True:
        try:
            item = await asyncio.wait_for(controller.workqueue.get(), timeout=0.05)
        except TimeoutError:
            return queued
        queued.add(item)
        controller.workqueue.done(item)


@pytest.mark.asyncio
async def test_only_desired_messages_of_accounts_enter_the_workqueue() -> None:
    bundle, _, _, _ = drivers()
    controller = controller_of(FakePool(None), bundle)

    assert await controller.on_desired_message(desired_message("account", "acc-1")) == "acc-1"
    assert await controller.on_desired_message(desired_message("account", "acc-1", "bsm")) is None
    assert await controller.on_desired_message(desired_message("user", "u-1")) is None
    assert await controller.on_desired_message(b"{invalido") is None

    assert await drain(controller) == {"acc-1"}
