"""Testes unitários do ciclo atômico de reconciliação do Controller (decisão 0096)."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ipm_serviceaccount.controller.drivers.serviceaccount import IdentityMachine
from ipm_serviceaccount.controller.engine.controller import (
    ControllerDrivers,
    ServiceAccountController,
)
from ipm_serviceaccount.controller.settings import ServiceAccountControllerSettings

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


@pytest.mark.asyncio
async def test_reconcile_creates_absent_serviceaccount_and_saves_observation() -> None:
    row: dict[str, Any] = {
        "resource_id": "sa-1",
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
            "name": "robot",
            "roles": ["ipm.serviceaccountViewer"],
            "deletionProtection": False,
            "keys": [],
        },
        "observed": {},
        "presence": None,
        "requested_by": "user-1",
        "correlation_id": "corr-1",
    }
    pool = FakePool(row)

    # 1ª observação: ausente; após a criação: presente e convergida.
    machines: Any = AsyncMock()
    authorizations: Any = AsyncMock()
    metadata: Any = AsyncMock()
    machines.get_machine.side_effect = [
        None,  # observação
        IdentityMachine("org-1", "USER_STATE_ACTIVE", "ACCESS_TOKEN_TYPE_JWT"),  # _create
        IdentityMachine("org-1", "USER_STATE_ACTIVE", "ACCESS_TOKEN_TYPE_JWT"),  # reobservação
    ]
    machines.create_machine.return_value = True
    machines.list_keys.return_value = []
    authorizations.authorization.return_value = None
    authorizations.granted_permissions.return_value = {
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
    }

    async def stored_metadata(_owner: str, key: str) -> str | None:
        return {"deletionProtection": "false"}.get(key)

    metadata.get_value.side_effect = stored_metadata

    controller = ServiceAccountController(
        cast("Any", pool),
        ControllerDrivers(machines=machines, authorizations=authorizations, metadata=metadata),
        ServiceAccountControllerSettings(),
        clock=lambda: NOW,
    )

    await controller.reconcile("sa-1")

    machines.create_machine.assert_awaited_once()
    authorizations.create.assert_awaited_once_with(
        "sa-1", "org-1", ["ipm.serviceaccount.get", "ipm.serviceaccount.list"]
    )
    statements = [(str(query), params) for query, params in pool.conn.executed]
    update = next(p for q, p in statements if "UPDATE ipm.serviceaccount SET observed" in q)
    assert "Ready" in update
    outbox = next(p for q, p in statements if "serviceaccount_outbox" in q)
    assert outbox[2] == "updated.ipm.serviceaccount.sa-1"


def _controller(row: dict[str, Any] | None = None) -> ServiceAccountController:
    return ServiceAccountController(
        cast("Any", FakePool(row)),
        ControllerDrivers(machines=AsyncMock(), authorizations=AsyncMock(), metadata=AsyncMock()),
        ServiceAccountControllerSettings(),
        clock=lambda: NOW,
    )


def _desired_message(resource_type: str, resource_id: str, data: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "messageId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "api",
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


async def _drain(controller: ServiceAccountController) -> set[str]:
    queued: set[str] = set()
    while True:
        try:
            item = await asyncio.wait_for(controller.workqueue.get(), timeout=0.05)
        except TimeoutError:
            return queued
        queued.add(item)
        controller.workqueue.done(item)


@pytest.mark.asyncio
async def test_a_role_change_requeues_only_the_serviceaccounts_that_have_it() -> None:
    controller = _controller()
    for sa_id, roles in (("sa-a", ["ipm.serviceaccountViewer"]), ("sa-b", ["ipm.userAdmin"])):
        await controller.on_desired_message(
            _desired_message(
                "serviceaccount",
                sa_id,
                {"lifecycle": "present", "organizationId": "org-1", "roles": roles},
            )
        )
    await _drain(controller)

    await controller.on_desired_message(
        _desired_message(
            "role",
            "role-1",
            {
                "lifecycle": "present",
                "name": "ipm.serviceaccountViewer",
                "permissions": ["ipm.serviceaccount.get"],
            },
        )
    )

    assert await _drain(controller) == {"sa-a"}
    assert controller.catalog.expand_roles(["ipm.serviceaccountViewer"], "org-1") == [
        "ipm.serviceaccount.get"
    ]


@pytest.mark.asyncio
async def test_an_unchanged_catalog_requeues_nobody() -> None:
    controller = _controller()
    await controller.on_desired_message(
        _desired_message(
            "serviceaccount",
            "sa-a",
            {
                "lifecycle": "present",
                "organizationId": "org-1",
                "roles": ["ipm.serviceaccountViewer"],
            },
        )
    )
    await _drain(controller)

    await controller.on_desired_message(
        _desired_message(
            "role",
            "role-1",
            {
                "lifecycle": "present",
                "name": "ipm.serviceaccountViewer",
                "permissions": controller.catalog.roles["ipm.serviceaccountViewer"],
            },
        )
    )

    assert await _drain(controller) == set()


@pytest.mark.asyncio
async def test_a_removed_serviceaccount_leaves_the_membership_index() -> None:
    controller = _controller()
    desired = {"lifecycle": "present", "organizationId": "org-1", "roles": ["ipm.userViewer"]}
    await controller.on_desired_message(_desired_message("serviceaccount", "sa-a", desired))
    assert len(controller.members) == 1

    await controller.on_desired_message(
        _desired_message("serviceaccount", "sa-a", {**desired, "lifecycle": "absent"})
    )

    assert len(controller.members) == 0
