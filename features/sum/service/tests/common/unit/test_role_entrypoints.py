"""Entrypoints dos papéis: a composição liga as tarefas certas e devolve o código da supervisão.

O runtime real (NATS, sinais) é trocado por um duplo; o que se verifica é a montagem do papel.
"""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any

import pytest

from sum_service.api import main as api_main
from sum_service.api.settings import SumServiceApiSettings
from sum_service.controller import main as controller_main
from sum_service.controller.settings import SumServiceControllerSettings
from sum_service.publisher import main as publisher_main
from sum_service.publisher.settings import SumServicePublisherSettings


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


CATALOG = '{"ipm": ["ipm.organization.get"]}'


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
    return fake


async def test_the_publisher_is_ready_while_no_permanent_failure_blocks_it(
    runtime: FakeRuntime,
) -> None:
    assert await publisher_main.run(SumServicePublisherSettings()) == 0
    assert runtime.started == ["publisher"]
    assert runtime.health.checks["publication"]() is True


async def test_the_api_serves_http_and_leaves_the_probes_to_the_app(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUM_SERVICE_API_AUTH_AUDIENCE", "project")
    monkeypatch.setenv("SUM_SERVICE_API_CATALOG_PERMISSIONS", CATALOG)
    assert await api_main.run(SumServiceApiSettings()) == 0
    assert runtime.started == [
        "ipm-organization-projection",
        "bsm-account-projection",
        "http",
    ]
    assert runtime.health_port is None
    assert len(runtime.closers) == 2


async def test_the_controller_rolls_out_the_catalog_before_the_consumers(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    rolled_out: list[object] = []

    async def roll_out_catalog(pool: object, catalog: object) -> int:
        rolled_out.append(catalog)
        assert runtime.started == []  # antes dos consumers (decisão 0079)
        return 0

    monkeypatch.setattr(controller_main, "roll_out_catalog", roll_out_catalog)
    monkeypatch.setenv("SUM_SERVICE_CONTROLLER_CATALOG_PERMISSIONS", CATALOG)
    assert await controller_main.run(SumServiceControllerSettings()) == 0
    assert rolled_out == [{"ipm": ("ipm.organization.get",)}]
    assert "desired" in runtime.started
    assert "account-removed" in runtime.started
    assert "worker-0" in runtime.started
    assert "periodic" in runtime.started
    assert len(runtime.closers) == 2
