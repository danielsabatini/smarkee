"""Ciclo atômico de reconciliação do Controller de `sum.service`, sem banco (decisão 0096)."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from sum_service.controller.drivers.authorization import Grant
from sum_service.controller.engine.controller import ControllerDrivers, ServiceController
from sum_service.controller.settings import SumServiceControllerSettings

NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
WANTED = ["ipm.organization.create", "ipm.organization.get"]
MANAGED = [*WANTED, "ipm.organization.delete"]


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


def row_of(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "resource_id": "link-1",
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
            "reconciliation": "active",
            "ownerAccountId": "acc-1",
            "service": "ipm",
            "servicePermissions": WANTED,
            "managedPermissions": MANAGED,
        },
        "observed": {},
        "presence": None,
        "requested_by": "acc-1",
        "correlation_id": "corr-1",
    }
    return {**base, **changes}


def drivers() -> tuple[ControllerDrivers, Any, Any]:
    users: Any = AsyncMock()
    users.exists.return_value = True
    authorizations: Any = AsyncMock()
    authorizations.project_of = MagicMock(return_value="p-ipm")
    return ControllerDrivers(users, authorizations), users, authorizations


def controller_of(pool: FakePool, bundle: ControllerDrivers) -> ServiceController:
    return ServiceController(
        cast("Any", pool), bundle, SumServiceControllerSettings(), clock=lambda: NOW
    )


def statements(pool: FakePool) -> list[tuple[str, tuple[Any, ...]]]:
    return [(str(query), params) for query, params in pool.conn.executed]


@pytest.mark.asyncio
async def test_reconcile_enables_the_link_and_saves_the_observation() -> None:
    pool = FakePool(row_of())
    bundle, _, authorizations = drivers()
    # observação e leituras da ação (conceder e revogar o que sobra) não acham nada; a
    # reobservação, depois da ação, acha
    authorizations.grants.side_effect = [[], [], [], [Grant("g-1", "p-ipm", frozenset(WANTED))]]

    retry = await controller_of(pool, bundle).reconcile("link-1")

    assert retry is False
    authorizations.create_grant.assert_awaited_once_with("acc-1", "p-ipm", WANTED)
    found = statements(pool)
    update = next(p for q, p in found if "UPDATE sum.service SET observed" in q)
    assert "Ready" in update
    outbox = next(p for q, p in found if "sum.service_outbox" in q)
    assert outbox[2] == "updated.sum.service.link-1"
    assert outbox[3].obj["correlationId"] == "corr-1"


@pytest.mark.asyncio
async def test_the_owner_is_the_provider_user_not_the_resource_id() -> None:
    pool = FakePool(row_of())
    bundle, users, authorizations = drivers()
    authorizations.grants.return_value = [Grant("g-1", "p-ipm", frozenset(WANTED))]

    await controller_of(pool, bundle).reconcile("link-1")

    users.exists.assert_awaited_with("acc-1")
    authorizations.grants.assert_awaited_with("acc-1")


@pytest.mark.asyncio
async def test_a_reevaluation_without_news_emits_nothing() -> None:
    def converged_drivers() -> ControllerDrivers:
        bundle, _, authorizations = drivers()
        authorizations.grants.return_value = [Grant("g-1", "p-ipm", frozenset(WANTED))]
        return bundle

    first = FakePool(row_of())
    await controller_of(first, converged_drivers()).reconcile("link-1")
    update = next(p for q, p in statements(first) if "UPDATE sum.service SET observed" in q)
    saved = row_of(
        phase="Ready",
        observed_generation=1,
        presence=update[1],
        observed=update[0].obj,
        conditions=update[3].obj,
    )

    again = FakePool(saved)
    bundle = converged_drivers()
    await controller_of(again, bundle).reconcile("link-1")

    cast("Any", bundle.authorizations).create_grant.assert_not_awaited()
    assert not any("sum.service_outbox" in q for q, _ in statements(again))


@pytest.mark.asyncio
async def test_a_converged_disable_keeps_the_row_and_emits_updated() -> None:
    desired = {
        "lifecycle": "absent",
        "reconciliation": "active",
        "ownerAccountId": "acc-1",
        "service": "ipm",
        "servicePermissions": [],
        "managedPermissions": MANAGED,
    }
    pool = FakePool(
        row_of(lifecycle="absent", desired=desired, desired_generation=3, phase="Reconciling")
    )
    bundle, _, authorizations = drivers()
    authorizations.grants.side_effect = [
        [Grant("g-1", "p-ipm", frozenset(WANTED))],  # observação
        [Grant("g-1", "p-ipm", frozenset(WANTED))],  # leitura da ação
        [],  # reobservação
    ]

    assert await controller_of(pool, bundle).reconcile("link-1") is False

    authorizations.remove_grant.assert_awaited_once_with("g-1")
    found = statements(pool)
    assert not any("DELETE FROM sum.service" in q for q, _ in found)  # decisão 0033
    update = next(p for q, p in found if "UPDATE sum.service SET observed" in q)
    assert "Ready" in update
    outbox = next(p for q, p in found if "sum.service_outbox" in q)
    payload = outbox[3].obj
    assert payload["data"]["lifecycle"] == "absent"
    assert "removed" not in payload["data"]


@pytest.mark.asyncio
async def test_a_missing_user_keeps_the_enabled_link_reconciling() -> None:
    pool = FakePool(row_of())
    bundle, users, authorizations = drivers()
    users.exists.return_value = False
    authorizations.grants.return_value = []

    assert await controller_of(pool, bundle).reconcile("link-1") is True  # volta à fila

    update = next(p for q, p in statements(pool) if "UPDATE sum.service SET observed" in q)
    assert "Reconciling" in update


@pytest.mark.asyncio
async def test_a_suspended_or_missing_resource_is_left_alone() -> None:
    for row in (None, row_of(reconciliation="suspended")):
        pool = FakePool(row)
        bundle, users, _ = drivers()
        assert await controller_of(pool, bundle).reconcile("link-1") is False
        users.exists.assert_not_awaited()


def desired_message(resource_type: str, resource_id: str, module: str = "sum") -> bytes:
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


async def drain(controller: ServiceController) -> set[str]:
    queued: set[str] = set()
    while True:
        try:
            item = await asyncio.wait_for(controller.workqueue.get(), timeout=0.05)
        except TimeoutError:
            return queued
        queued.add(item)
        controller.workqueue.done(item)


@pytest.mark.asyncio
async def test_only_desired_messages_of_service_links_enter_the_workqueue() -> None:
    bundle, _, _ = drivers()
    controller = controller_of(FakePool(None), bundle)

    assert await controller.on_desired_message(desired_message("service", "link-1")) == "link-1"
    assert await controller.on_desired_message(desired_message("service", "link-1", "ipm")) is None
    assert await controller.on_desired_message(desired_message("account", "acc-1", "core")) is None
    assert await controller.on_desired_message(b"{invalido") is None

    assert await drain(controller) == {"link-1"}
