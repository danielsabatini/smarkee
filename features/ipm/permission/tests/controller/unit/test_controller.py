"""Testes unitários do ciclo atômico de reconciliação do Controller (decisão 0096)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ipm_permission.controller.drivers.project_role import IdentityProjectRole
from ipm_permission.controller.engine.controller import ControllerDrivers, PermissionController
from ipm_permission.controller.settings import PermissionControllerSettings

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
async def test_reconcile_creates_absent_permission_and_saves_observation() -> None:
    row: dict[str, Any] = {
        "resource_id": "perm-1",
        "desired_generation": 1,
        "observed_generation": 0,
        "resource_version": 1,
        "lifecycle": "present",
        "reconciliation": "active",
        "failure_count": 0,
        "phase": "Pending",
        "conditions": [],
        "desired": {
            "name": "ipm.thing.get",
            "description": "Ler coisas",
            "lifecycle": "present",
        },
        "observed": {},
        "presence": None,
        "requested_by": "user-1",
        "correlation_id": "corr-1",
    }
    pool = FakePool(row)

    # 1ª observação: ausente; após a criação: presente e convergida.
    roles: Any = AsyncMock()
    roles.get.side_effect = [
        None,
        IdentityProjectRole(key="ipm.thing.get", display_name="Ler coisas", group="ipm"),
    ]

    controller = PermissionController(
        cast("Any", pool),
        ControllerDrivers(roles=roles),
        PermissionControllerSettings(),
        clock=lambda: NOW,
    )

    await controller.reconcile("perm-1")

    roles.add_or_update_role.assert_awaited_once_with(
        "ipm.thing.get", display_name="Ler coisas", group="ipm"
    )
    statements = [(str(query), params) for query, params in pool.conn.executed]
    # Estado gravado com fase aceita pelo CHECK do SSOT e geração confirmada.
    update = next(p for q, p in statements if "UPDATE ipm.permission SET observed" in q)
    assert "Ready" in update
    # `updated` no outbox, na mesma transação.
    outbox = next(p for q, p in statements if "permission_outbox" in q)
    assert outbox[2] == "updated.ipm.permission.perm-1"
