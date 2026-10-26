"""Provedor do Observer no banco `platform`: leitura, ausência e falha (pool simulado)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from ipm_group.observer.domain.identity import ProviderError
from ipm_group.observer.provider.storage import StateStoreConnection


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class FakeConnection:
    def __init__(self, row: tuple[Any, ...] | None, error: Exception | None) -> None:
        self.calls: list[str] = []
        self._row = row
        self._error = error

    async def execute(self, sql: str, params: tuple[Any, ...]) -> FakeCursor:
        if self._error is not None:
            raise self._error
        self.calls.append(sql)
        return FakeCursor(self._row)


class FakePool:
    def __init__(self, row: tuple[Any, ...] | None = None, error: Exception | None = None) -> None:
        self.connection_used = FakeConnection(row, error)

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[FakeConnection]:
        yield self.connection_used


def store(pool: FakePool) -> StateStoreConnection:
    return StateStoreConnection(cast("AsyncConnectionPool[Any]", pool))


async def test_read_maps_the_row_and_only_selects() -> None:
    pool = FakePool(("org-1", "auditors", "d", True, ["core.accountViewer", "ipm.userViewer"]))
    assert await store(pool).read_record("group-1") == {
        "organizationId": "org-1",
        "name": "auditors",
        "description": "d",
        "deletionProtection": True,
        "roles": ["core.accountViewer", "ipm.userViewer"],
    }
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in pool.connection_used.calls)


async def test_missing_group_is_none() -> None:
    assert await store(FakePool(None)).read_record("group-1") is None


async def test_invalid_resource_id_is_a_provider_error_before_any_query() -> None:
    pool = FakePool()
    with pytest.raises(ProviderError):
        await store(pool).read_record("Group_1")
    assert pool.connection_used.calls == []


async def test_database_failure_is_a_provider_error_and_does_not_leak_the_message() -> None:
    pool = FakePool(error=psycopg.OperationalError("password=segredo host=db"))
    with pytest.raises(ProviderError) as exc_info:
        await store(pool).read_record("group-1")
    assert "segredo" not in str(exc_info.value)
