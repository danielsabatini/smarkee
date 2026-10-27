"""Entrypoints dos papéis: a composição liga as tarefas certas e devolve o código da supervisão.

O runtime real (NATS, sinais) é trocado por um duplo; o que se verifica é a montagem do papel.
"""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any

import pytest

from ipm_organization.controller import main as controller_main
from ipm_organization.controller.settings import OrganizationControllerSettings
from ipm_organization.manager import main as manager_main
from ipm_organization.manager.settings import OrganizationManagerSettings
from ipm_organization.publisher import main as publisher_main
from ipm_organization.publisher.settings import IpmOrganizationPublisherSettings
from ipm_organization.receiver import main as receiver_main
from ipm_organization.receiver.settings import OrganizationReceiverSettings


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
        self.rolled_out_kind: Any = None

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
        controller_main,
        manager_main,
        publisher_main,
        receiver_main,
    )
    for module in modules:
        monkeypatch.setattr(module, "role_runtime", fake_role_runtime)
    for module in (controller_main, manager_main, receiver_main):
        monkeypatch.setattr(module, "open_pool", fake_open_pool)

    async def fake_rollout(_pool: Any, kind: Any) -> int:
        fake.started.append("user-access-rollout")
        fake.rolled_out_kind = kind
        return 0

    monkeypatch.setattr(manager_main, "roll_out_user_access", fake_rollout)
    for prefix in (
        "IPM_ORGANIZATION_OBSERVER_",
        "IPM_ORGANIZATION_EXECUTOR_",
        "IPM_ORGANIZATION_CONTROLLER_",
    ):
        monkeypatch.setenv(f"{prefix}IDENTITY_PROJECT_ID", "roles-ipm")
    for account in ("EXECUTOR", "OBSERVER"):
        monkeypatch.setenv(
            f"IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_{account}_ACCOUNT_ID", f"user-{account}"
        )
        monkeypatch.setenv(
            f"IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_{account}_ACCOUNT_ID",
            f"machine-{account}",
        )
    monkeypatch.setenv(
        "IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_CONTROLLER_ACCOUNT_ID",
        "machine-CONTROLLER",
    )
    monkeypatch.setenv(
        "IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_CONTROLLER_ACCOUNT_ID", "user-CONTROLLER"
    )
    return fake


async def test_the_controller_starts_informer_workers_and_periodic(
    runtime: FakeRuntime,
) -> None:
    settings = OrganizationControllerSettings()
    assert await controller_main.run(settings) == 0
    assert "desired" in runtime.started
    assert "worker-0" in runtime.started
    assert "worker-1" in runtime.started
    assert "periodic" in runtime.started
    assert len(runtime.closers) == 2


async def test_the_manager_starts_one_task_per_consumer(runtime: FakeRuntime) -> None:
    assert await manager_main.run(OrganizationManagerSettings()) == 0
    # O rollout do `userAccess` vem antes dos consumers (decisões 0081 e 0083).
    assert runtime.started == [
        "user-access-rollout",
        "requested",
        "permissions",
    ]
    rolled_out = runtime.rolled_out_kind.policy.rolled_out({"lifecycle": "present"})
    assert rolled_out["userAccess"]["userExecutorAccountId"] == "user-EXECUTOR"
    assert rolled_out["userAccess"]["serviceaccountExecutorAccountId"] == "machine-EXECUTOR"
    assert len(runtime.closers) == 1


async def test_the_publisher_is_ready_while_no_permanent_failure_blocks_it(
    runtime: FakeRuntime,
) -> None:
    assert await publisher_main.run(IpmOrganizationPublisherSettings()) == 0
    assert runtime.started == ["publisher"]
    assert runtime.health.checks["publication"]() is True


async def test_the_receiver_serves_http_and_leaves_the_probes_to_the_app(
    runtime: FakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE", "project")
    assert await receiver_main.run(OrganizationReceiverSettings()) == 0
    assert runtime.started == ["http"]
    assert runtime.health_port is None
    assert len(runtime.closers) == 2
