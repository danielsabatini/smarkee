"""Entrypoints dos papéis: a composição liga as tarefas certas e devolve o código da supervisão.

O runtime real (NATS, sinais) é trocado por um duplo; o que se verifica é a montagem do papel.
"""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any

import pytest

from sum_service.common.lifecycle import InvalidConfigurationError
from sum_service.executor import main as executor_main
from sum_service.manager import main as manager_main
from sum_service.observer import main as observer_main
from sum_service.publisher import main as publisher_main
from sum_service.receiver import main as receiver_main
from sum_service.reconciler import main as reconciler_main

CATALOG = '{"ipm": ["ipm.organization.get"]}'


class FakeHealth:
    def beat(self) -> None:
        return

    def add_check(self, name: str, check: Any) -> None:
        self.last_check = (name, check)


class FakeRuntime:
    def __init__(self) -> None:
        self.stream: Any = object()
        self.stop = asyncio.Event()
        self.health = FakeHealth()
        self.started: list[str] = []
        self.closers: list[Any] = []
        self.health_port: int | None = -1

    def start(self, name: str, work: Coroutine[Any, Any, None]) -> None:
        work.close()
        self.started.append(name)

    def close_after(self, closer: Any) -> None:
        self.closers.append(closer)

    async def serve(self, *, health_port: int | None) -> int:
        self.health_port = health_port
        return 0


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> FakeRuntime:
    fake = FakeRuntime()

    @asynccontextmanager
    async def fake_role_runtime(*_: Any, **__: Any) -> AsyncGenerator[FakeRuntime]:
        yield fake

    for module in (
        executor_main,
        manager_main,
        observer_main,
        publisher_main,
        receiver_main,
        reconciler_main,
    ):
        monkeypatch.setattr(module, "role_runtime", fake_role_runtime)
    for role in ("MANAGER", "OBSERVER", "EXECUTOR", "RECONCILER", "PUBLISHER", "RECEIVER"):
        monkeypatch.setenv(f"SUM_SERVICE_{role}_MESSAGING_PASSWORD", "x")
    monkeypatch.setenv("SUM_SERVICE_MANAGER_CATALOG_PERMISSIONS", CATALOG)
    return fake


async def test_the_reconciler_starts_one_consumer_per_stream_and_the_periodic_loop(
    runtime: FakeRuntime,
) -> None:
    settings = reconciler_main.SumServiceReconcilerSettings()
    assert await reconciler_main.run(settings) == 0
    assert "periodic" in runtime.started
    assert len(runtime.started) == len(reconciler_main.STREAMS) + 1


async def test_the_manager_starts_every_consumer(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Pool:
        async def close(self) -> None:
            return

    async def open_pool(*_: Any, **__: Any) -> Pool:
        return Pool()

    rolled_out: list[object] = []

    async def roll_out_catalog(pool: object, catalog: object) -> int:
        rolled_out.append(catalog)
        return 0

    monkeypatch.setattr(manager_main, "open_pool", open_pool)
    monkeypatch.setattr(manager_main, "roll_out_catalog", roll_out_catalog)
    monkeypatch.setenv("SUM_SERVICE_MANAGER_DATABASE_PASSWORD", "x")
    settings = manager_main.SumServiceManagerSettings()
    assert await manager_main.run(settings) == 0
    assert runtime.started == ["requested", "observed", "completed", "failed", "account_removed"]
    assert rolled_out == [{"ipm": ("ipm.organization.get",)}]  # antes dos consumers (decisão 0079)
    assert len(runtime.closers) == 1


async def test_the_observer_starts_the_state_consumers_and_the_periodic_loop(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID", "1")
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_IDENTITY_PROJECT_IDS", '{"ipm": "2"}')
    settings = observer_main.SumServiceObserverSettings()
    assert await observer_main.run(settings) == 0
    assert "periodic" in runtime.started
    assert len(runtime.started) == len(observer_main.STREAMS) + 1


async def test_the_executor_starts_one_consumer_per_partition(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_IDENTITY_REGISTER_ORGANIZATION_ID", "1")
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_IDENTITY_PROJECT_IDS", '{"ipm": "2"}')
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_PARTITION_COUNT", "3")
    settings = executor_main.SumServiceExecutorSettings()
    assert await executor_main.run(settings) == 0
    assert runtime.started == ["action-p0", "action-p1", "action-p2"]


async def test_the_publisher_is_ready_unless_a_permanent_failure_blocks_it(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD", "x")
    settings = publisher_main.SumServicePublisherSettings()
    assert await publisher_main.run(settings) == 0
    assert runtime.started == ["publisher"]
    name, check = runtime.health.last_check  # type: ignore[attr-defined]
    assert name == "publication"
    assert check() is True


async def test_the_receiver_serves_http_and_leaves_the_probes_to_the_app(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Pool:
        async def close(self) -> None:
            return

    async def open_pool(*_: Any, **__: Any) -> Pool:
        return Pool()

    monkeypatch.setattr(receiver_main, "open_pool", open_pool)
    monkeypatch.setenv("SUM_SERVICE_RECEIVER_DATABASE_PASSWORD", "x")
    monkeypatch.setenv("SUM_SERVICE_RECEIVER_AUTH_AUDIENCE", "project")
    settings = receiver_main.SumServiceReceiverSettings()
    assert await receiver_main.run(settings) == 0
    assert runtime.started == ["http"]
    assert runtime.health_port is None
    assert len(runtime.closers) == 2


def test_an_invalid_catalog_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_MANAGER_CATALOG_PERMISSIONS", "not json")
    settings = manager_main.SumServiceManagerSettings()
    with pytest.raises(InvalidConfigurationError):
        manager_main.validate(settings)


@pytest.mark.parametrize("module", [observer_main, executor_main])
def test_only_the_manager_has_the_catalog(module: ModuleType) -> None:
    """O catálogo tem uma fonte só (decisão 0079): o Observer e o Executor usam o `desired`."""
    role = module.__name__.split(".")[-2].capitalize()
    settings_type = getattr(module, f"SumService{role}Settings")
    assert "catalog" not in settings_type.model_fields
    assert not hasattr(module, "validate")
