"""Entrypoints dos papéis: a composição liga as tarefas certas e devolve o código da supervisão.

O runtime real (NATS, sinais) é trocado por um duplo; o que se verifica é a montagem do papel.
"""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any

import pytest

from bsm_account.executor import main as executor_main
from bsm_account.executor.settings import AccountExecutorSettings
from bsm_account.manager import main as manager_main
from bsm_account.manager.settings import AccountManagerSettings
from bsm_account.observer import main as observer_main
from bsm_account.observer.settings import AccountObserverSettings
from bsm_account.publisher import main as publisher_main
from bsm_account.publisher.settings import BsmAccountPublisherSettings
from bsm_account.receiver import main as receiver_main
from bsm_account.receiver.settings import AccountReceiverSettings
from bsm_account.reconciler import main as reconciler_main
from bsm_account.reconciler.settings import AccountReconcilerSettings


class FakeHealth:
    def __init__(self) -> None:
        self.checks: dict[str, Any] = {}

    def beat(self) -> None:
        return

    def add_check(self, name: str, check: Any) -> None:
        self.checks[name] = check


class FakeClient:
    is_connected = True


class FakeRuntime:
    """Registra o que o papel liga, sem executar nenhuma das tarefas."""

    def __init__(self) -> None:
        self.stream: Any = object()
        self.client = FakeClient()
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


class FakePool:
    async def close(self) -> None:
        return


async def fake_open_pool(*_: Any, **__: Any) -> FakePool:
    return FakePool()


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> FakeRuntime:
    fake = FakeRuntime()

    @asynccontextmanager
    async def fake_role_runtime(*_: Any, **__: Any) -> AsyncGenerator[FakeRuntime]:
        yield fake

    modules: tuple[ModuleType, ...] = (
        executor_main,
        manager_main,
        observer_main,
        publisher_main,
        receiver_main,
        reconciler_main,
    )
    for module in modules:
        monkeypatch.setattr(module, "role_runtime", fake_role_runtime)
    for module in (manager_main, receiver_main):
        monkeypatch.setattr(module, "open_pool", fake_open_pool)
    for prefix in ("BSM_ACCOUNT_OBSERVER_", "BSM_ACCOUNT_EXECUTOR_"):
        monkeypatch.setenv(f"{prefix}STORAGE_DIRECTORY", "/srv/bsm-state")
    return fake


async def test_the_manager_starts_one_task_per_consumer(runtime: FakeRuntime) -> None:
    assert await manager_main.run(AccountManagerSettings()) == 0
    assert runtime.started == ["requested", "observed", "result", "account_updated"]
    assert len(runtime.closers) == 1


async def test_the_observer_starts_the_state_consumers_and_the_periodic_loop(
    runtime: FakeRuntime,
) -> None:
    assert await observer_main.run(AccountObserverSettings()) == 0
    assert runtime.started[-1] == "periodic"
    assert len(runtime.started) == len(observer_main.STREAMS) + 1


async def test_the_executor_starts_one_consumer_per_partition(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BSM_ACCOUNT_EXECUTOR_PARTITION_COUNT", "3")
    assert await executor_main.run(AccountExecutorSettings()) == 0
    assert runtime.started == ["action-p0", "action-p1", "action-p2"]


async def test_the_reconciler_starts_the_state_consumers_and_the_periodic_loop(
    runtime: FakeRuntime,
) -> None:
    assert await reconciler_main.run(AccountReconcilerSettings()) == 0
    assert runtime.started[-1] == "periodic"
    assert len(runtime.started) == len(reconciler_main.STREAMS) + 1


async def test_the_publisher_is_ready_while_no_permanent_failure_blocks_it(
    runtime: FakeRuntime,
) -> None:
    assert await publisher_main.run(BsmAccountPublisherSettings()) == 0
    assert runtime.started == ["publisher"]
    assert runtime.health.checks["publication"]() is True


async def test_the_receiver_serves_http_and_leaves_the_probes_to_the_app(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BSM_ACCOUNT_RECEIVER_AUTH_AUDIENCE", "project")
    assert await receiver_main.run(AccountReceiverSettings()) == 0
    assert runtime.started == ["http"]
    assert runtime.health_port is None
    assert len(runtime.closers) == 2
