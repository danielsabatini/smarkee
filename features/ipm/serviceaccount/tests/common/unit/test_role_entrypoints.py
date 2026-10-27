"""Entrypoints dos papéis: a composição liga as tarefas certas e devolve o código da supervisão.

O runtime real (NATS, sinais) é trocado por um duplo; o que se verifica é a montagem do papel.
"""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any

import pytest

from ipm_serviceaccount.api import main as api_main
from ipm_serviceaccount.api.settings import ServiceaccountApiSettings
from ipm_serviceaccount.controller import main as controller_main
from ipm_serviceaccount.controller.settings import ServiceAccountControllerSettings
from ipm_serviceaccount.publisher import main as publisher_main
from ipm_serviceaccount.publisher.settings import IpmServiceaccountPublisherSettings


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
        api_main,
        controller_main,
        publisher_main,
    )
    for module in modules:
        monkeypatch.setattr(module, "role_runtime", fake_role_runtime)
    for module in (api_main, controller_main):
        monkeypatch.setattr(module, "open_pool", fake_open_pool)
    monkeypatch.setenv("IPM_SERVICEACCOUNT_CONTROLLER_IDENTITY_PROJECT_ID", "roles-ipm")
    return fake


async def test_the_publisher_is_ready_while_no_permanent_failure_blocks_it(
    runtime: FakeRuntime,
) -> None:
    assert await publisher_main.run(IpmServiceaccountPublisherSettings()) == 0
    assert runtime.started == ["publisher"]
    assert runtime.health.checks["publication"]() is True


async def test_the_api_serves_http_and_leaves_the_probes_to_the_app(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_API_AUTH_AUDIENCE", "project")
    assert await api_main.run(ServiceaccountApiSettings()) == 0
    assert runtime.started == ["permissions", "roles", "http"]
    assert runtime.health_port is None
    assert len(runtime.closers) == 2


async def test_the_controller_starts_informer_workers_and_periodic(
    runtime: FakeRuntime,
) -> None:
    assert await controller_main.run(ServiceAccountControllerSettings()) == 0
    for informer in ("desired", "permissions", "roles"):
        assert informer in runtime.started
    assert "worker-0" in runtime.started
    assert "periodic" in runtime.started
    assert len(runtime.closers) == 2
