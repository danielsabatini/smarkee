"""Provedor do Executor no banco `platform`: SQL, transação e tradução de erros (pool simulado)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from ipm_group.executor.domain.identity import ProviderError
from ipm_group.executor.provider.storage import StateStoreConnection


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class FakeConnection:
    def __init__(self, row: tuple[Any, ...] | None, error: Exception | None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.transactions = 0
        self._row = row
        self._error = error

    async def execute(self, sql: str, params: tuple[Any, ...]) -> FakeCursor:
        if self._error is not None:
            raise self._error
        self.calls.append((" ".join(sql.split()), params))
        return FakeCursor(self._row)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        self.transactions += 1
        yield


class FakePool:
    def __init__(self, row: tuple[Any, ...] | None = None, error: Exception | None = None) -> None:
        self.connection_used = FakeConnection(row, error)

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[FakeConnection]:
        yield self.connection_used


def store(pool: FakePool) -> StateStoreConnection:
    return StateStoreConnection(cast("AsyncConnectionPool[Any]", pool))


RECORD = {
    "organizationId": "org-1",
    "name": "auditors",
    "description": "d",
    "deletionProtection": True,
    "roles": ["core.accountViewer", "ipm.userViewer"],
}


async def test_write_runs_in_one_transaction_with_parameters_only() -> None:
    pool = FakePool()
    await store(pool).write_record("group-1", RECORD)

    connection = pool.connection_used
    assert connection.transactions == 1
    assert [sql.split()[0] for sql, _ in connection.calls] == ["INSERT", "DELETE", "INSERT"]
    assert connection.calls[0][1] == ("group-1", "org-1", "auditors", "d", True)
    assert connection.calls[1][1] == ("group-1", ["core.accountViewer", "ipm.userViewer"])
    assert all("group-1" not in sql and "auditors" not in sql for sql, _ in connection.calls)


async def test_read_maps_the_row_to_a_record_and_missing_to_none() -> None:
    row = ("org-1", "auditors", "d", False, ["ipm.userViewer"])
    assert await store(FakePool(row)).read_record("group-1") == {
        "organizationId": "org-1",
        "name": "auditors",
        "description": "d",
        "deletionProtection": False,
        "roles": ["ipm.userViewer"],
    }
    assert await store(FakePool(None)).read_record("group-1") is None


async def test_delete_is_a_single_parameterized_statement() -> None:
    pool = FakePool()
    await store(pool).delete_record("group-1")
    assert pool.connection_used.calls == [
        ("DELETE FROM ipm.group WHERE resource_id = %s", ("group-1",))
    ]


@pytest.mark.parametrize(
    "resource_id", ["", "Group", "group_1", "-group", "group-", "a" * 129, "x'; --"]
)
async def test_invalid_resource_id_is_rejected_before_any_query(resource_id: str) -> None:
    pool = FakePool()
    with pytest.raises(ProviderError) as exc_info:
        await store(pool).write_record(resource_id, RECORD)
    assert (exc_info.value.reason, exc_info.value.retryable) == ("Rejected", False)
    assert pool.connection_used.calls == []


async def test_constraint_violation_is_rejected_without_retry() -> None:
    pool = FakePool(error=psycopg.errors.UniqueViolation("duplicate"))
    with pytest.raises(ProviderError) as exc_info:
        await store(pool).write_record("group-1", RECORD)
    assert (exc_info.value.reason, exc_info.value.retryable) == ("Rejected", False)


async def test_connection_failure_is_retryable_and_does_not_leak_the_message() -> None:
    pool = FakePool(error=psycopg.OperationalError("password=segredo host=db"))
    with pytest.raises(ProviderError) as exc_info:
        await store(pool).read_record("group-1")
    assert (exc_info.value.reason, exc_info.value.retryable) == ("ExternalError", True)
    assert "segredo" not in str(exc_info.value)
