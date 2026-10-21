"""Ciclo de vida de um papel: sinais, supervisão das tarefas e validação da configuração."""

import asyncio
import logging
import os
import signal

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from ipm_user.common import lifecycle
from ipm_user.common.lifecycle import (
    EXIT_INVALID_CONFIGURATION,
    InvalidConfigurationError,
    start_role,
    stop_on_signals,
    supervise,
)


async def wait_for(stop: asyncio.Event) -> None:
    await stop.wait()


async def test_a_stop_request_ends_every_task_and_exits_with_zero() -> None:
    stop = asyncio.Event()
    tasks = {name: asyncio.create_task(wait_for(stop)) for name in ("a", "b")}
    asyncio.get_running_loop().call_later(0.01, stop.set)
    assert await supervise(tasks, stop) == 0
    assert all(task.done() for task in tasks.values())


async def test_a_task_that_ends_by_itself_stops_the_others_and_exits_with_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()

    async def ends() -> None:
        return

    tasks = {"ends": asyncio.create_task(ends()), "waits": asyncio.create_task(wait_for(stop))}
    with caplog.at_level(logging.ERROR, logger=lifecycle.logger.name):
        assert await supervise(tasks, stop) == 1
    assert stop.is_set()
    assert tasks["waits"].done()
    unexpected = [r for r in caplog.records if r.getMessage() == "task stopped unexpectedly"]
    assert [r.__dict__["smarkee.task.name"] for r in unexpected] == ["ends"]


async def test_a_task_that_fails_is_logged_without_hiding_the_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()

    async def fails() -> None:
        raise ValueError

    tasks = {"fails": asyncio.create_task(fails())}
    with caplog.at_level(logging.ERROR, logger=lifecycle.logger.name):
        assert await supervise(tasks, stop) == 1
    failed = [r for r in caplog.records if r.getMessage() == "task failed"]
    assert failed
    assert failed[0].exc_info is not None
    assert failed[0].exc_info[0] is ValueError


async def test_sigterm_sets_the_stop_event() -> None:
    stop = stop_on_signals()
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(stop.wait(), timeout=2.0)
    finally:
        loop = asyncio.get_running_loop()
        loop.remove_signal_handler(signal.SIGINT)
        loop.remove_signal_handler(signal.SIGTERM)
    assert stop.is_set()


# ---------------------------------------------------------------- start_role


class DummySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DUMMY_ROLE_")

    secret: str | None = None


def missing(settings: DummySettings) -> list[str]:
    return [] if settings.secret else ["DUMMY_ROLE_SECRET"]


@pytest.fixture(autouse=True)
def keep_pytest_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """`configure_logging` troca os handlers da raiz; os testes mantêm os do pytest."""

    def no_op(*, role: str) -> None: ...

    monkeypatch.setattr(lifecycle, "configure_logging", no_op)


def test_missing_configuration_exits_with_the_invalid_configuration_code_without_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("DUMMY_ROLE_SECRET", raising=False)
    ran = False

    async def run(settings: DummySettings) -> int:
        nonlocal ran
        ran = True
        return 0

    with (
        caplog.at_level(logging.ERROR, logger=lifecycle.logger.name),
        pytest.raises(SystemExit) as raised,
    ):
        start_role("dummy", DummySettings, missing, run)
    assert raised.value.code == EXIT_INVALID_CONFIGURATION
    assert not ran
    record = next(r for r in caplog.records if r.getMessage() == "missing required configuration")
    assert record.__dict__["smarkee.config.missing_variables"] == ["DUMMY_ROLE_SECRET"]


@pytest.mark.parametrize("code", [0, 1])
def test_a_complete_configuration_runs_the_role_and_exits_with_its_code(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setenv("DUMMY_ROLE_SECRET", "valor")
    seen: list[str | None] = []

    async def run(settings: DummySettings) -> int:
        seen.append(settings.secret)
        return code

    with pytest.raises(SystemExit) as raised:
        start_role("dummy", DummySettings, missing, run)
    assert raised.value.code == code
    assert seen == ["valor"]


def test_an_invalid_configuration_exits_with_the_invalid_configuration_code_without_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DUMMY_ROLE_SECRET", "valor")
    ran = False

    async def run(settings: DummySettings) -> int:
        nonlocal ran
        ran = True
        return 0

    def validate(settings: DummySettings) -> None:
        raise InvalidConfigurationError("catalog is not valid JSON")

    with (
        caplog.at_level(logging.ERROR, logger=lifecycle.logger.name),
        pytest.raises(SystemExit) as raised,
    ):
        start_role("dummy", DummySettings, missing, run, validate=validate)
    assert raised.value.code == EXIT_INVALID_CONFIGURATION
    assert not ran
    record = next(r for r in caplog.records if r.getMessage() == "invalid configuration")
    assert record.__dict__["smarkee.reason"] == "catalog is not valid JSON"
