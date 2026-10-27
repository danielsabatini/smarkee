"""Testes unitários do ciclo atômico de reconciliação do Controller (decisão 0096)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ipm_organization.controller.drivers.organization import IdentityOrganization
from ipm_organization.controller.engine.controller import ControllerDrivers, OrganizationController
from ipm_organization.controller.settings import OrganizationControllerSettings

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
async def test_reconcile_creates_absent_organization_and_saves_observation() -> None:
    row: dict[str, Any] = {
        "resource_id": "org-1",
        "desired_generation": 1,
        "observed_generation": 0,
        "resource_version": 1,
        "lifecycle": "present",
        "reconciliation": "active",
        "failure_count": 0,
        "phase": "Pending",
        "conditions": [],
        "desired": {"name": "acme", "platformAccess": "granted", "lifecycle": "present"},
        "observed": {},
        "presence": None,
        "requested_by": "user-1",
        "correlation_id": "corr-1",
    }
    pool = FakePool(row)

    # 1ª observação: ausente; após a criação: presente e convergido.
    organizations: Any = AsyncMock()
    metadata: Any = AsyncMock()
    user_access: Any = AsyncMock()
    organizations.get_organization.side_effect = [
        None,
        IdentityOrganization(name="acme", active=True),
    ]
    organizations.create_organization.return_value = True
    metadata.get_value.return_value = "true"
    user_access.grant_permissions.return_value = []
    user_access.list_administrators.return_value = []

    controller = OrganizationController(
        cast("Any", pool),
        ControllerDrivers(organizations=organizations, metadata=metadata, user_access=user_access),
        OrganizationControllerSettings(),
        clock=lambda: NOW,
    )

    await controller.reconcile("org-1")

    organizations.create_organization.assert_awaited_once_with("org-1", name="acme")
    statements = [(str(query), params) for query, params in pool.conn.executed]
    # Estado gravado com fase aceita pelo CHECK do SSOT e geração confirmada.
    update = next(p for q, p in statements if "UPDATE ipm.organization SET observed" in q)
    assert "Ready" in update
    # `updated` no outbox, na mesma transação.
    outbox = next(p for q, p in statements if "organization_outbox" in q)
    assert outbox[2] == "manager.updated.ipm.organization.org-1.changed"
