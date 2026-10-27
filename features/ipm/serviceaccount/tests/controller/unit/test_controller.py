"""Testes unitários do ciclo atômico de reconciliação do Controller (decisão 0096)."""

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
            "permissions": ["ipm.serviceaccount.get"],
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
    authorizations.granted_permissions.return_value = {"ipm.serviceaccount.get"}

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
    authorizations.create.assert_awaited_once_with("sa-1", "org-1", ["ipm.serviceaccount.get"])
    statements = [(str(query), params) for query, params in pool.conn.executed]
    update = next(p for q, p in statements if "UPDATE ipm.serviceaccount SET observed" in q)
    assert "Ready" in update
    assert any("completed" in p for q, p in statements if "serviceaccount_operation" in q)
    outbox = next(p for q, p in statements if "serviceaccount_outbox" in q)
    assert outbox[2] == "manager.updated.ipm.serviceaccount.sa-1.changed"
