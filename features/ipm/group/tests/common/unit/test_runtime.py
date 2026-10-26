"""Ciclo de vida de um papel em execução: tarefas, saúde e ordem do encerramento."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from ipm_group.common import runtime as runtime_module
from ipm_group.common.runtime import role_runtime
from ipm_group.common.settings import MessagingSettings


@dataclass
class FakeClient:
    events: list[str] = field(default_factory=lambda: [])
    is_connected: bool = True
    drain_fails: bool = False

    def jetstream(self) -> object:
        return object()

    async def drain(self) -> None:
        self.events.append("drain")
        if self.drain_fails:
            raise OSError("connection lost")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    fake = FakeClient()

    async def connect(_: MessagingSettings, *, name: str) -> Any:
        fake.events.append(f"connect:{name}")
        return fake

    monkeypatch.setattr(runtime_module, "connect", connect)
    return fake


async def wait(stop: asyncio.Event) -> None:
    await stop.wait()


def closer(events: list[str], name: str) -> Any:
    async def close() -> None:
        events.append(name)

    return close


async def test_a_stop_request_ends_the_tasks_and_closes_in_order(client: FakeClient) -> None:
    async with role_runtime(MessagingSettings(), name="x-manager") as runtime:
        runtime.close_after(closer(client.events, "pool"))
        runtime.close_after(closer(client.events, "http"))
        runtime.start("work", wait(runtime.stop))
        asyncio.get_running_loop().call_later(0.01, runtime.stop.set)
        assert await runtime.serve(health_port=None) == 0
        assert runtime.health.ready()[0] is True
    # A conexão drena primeiro; os recursos fecham na ordem inversa do registro.
    assert client.events == ["connect:x-manager", "drain", "http", "pool"]


async def test_a_failure_while_building_still_drains_and_closes(client: FakeClient) -> None:
    with pytest.raises(RuntimeError):
        async with role_runtime(MessagingSettings(), name="x-executor") as runtime:
            runtime.close_after(closer(client.events, "pool"))
            raise RuntimeError("bad wiring")
    assert client.events == ["connect:x-executor", "drain", "pool"]


async def test_a_drain_failure_does_not_skip_the_other_resources(client: FakeClient) -> None:
    client.drain_fails = True
    async with role_runtime(MessagingSettings(), name="x-publisher") as runtime:
        runtime.close_after(closer(client.events, "pool"))
    assert client.events == ["connect:x-publisher", "drain", "pool"]


async def test_the_readiness_follows_the_messaging_connection(client: FakeClient) -> None:
    async with role_runtime(MessagingSettings(), name="x-observer") as runtime:
        runtime.health.mark_started()
        client.is_connected = False
        assert runtime.health.ready()[0] is False


async def test_a_task_name_is_used_once(client: FakeClient) -> None:
    async with role_runtime(MessagingSettings(), name="x-reconciler") as runtime:
        runtime.start("work", wait(runtime.stop))
        with pytest.raises(ValueError, match="already started"):
            runtime.start("work", wait(runtime.stop))
        runtime.stop.set()
        assert await runtime.serve(health_port=None) == 0
