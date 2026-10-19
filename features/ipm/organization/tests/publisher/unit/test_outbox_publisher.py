"""Laço do Publisher e publicação de um lote, com o banco e o transporte trocados por duplos."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Self, cast

import psycopg
import pytest

from ipm_organization.common.ports import PublishError
from ipm_organization.publisher.domain.publication import PublicationResult
from ipm_organization.publisher.outbox import publication as module
from ipm_organization.publisher.outbox.publication import OutboxPublisher, publish_pending
from ipm_organization.publisher.settings import DatabaseSettings

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class FakeCursor:
    def __init__(self, rows: Sequence[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_: Any, **__: Any) -> None:
        return

    async def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class FakeConnection:
    """Conexão que registra os comandos e serve as linhas do outbox."""

    def __init__(self, rows: Sequence[dict[str, Any]] = ()) -> None:
        self.rows = rows
        self.statements: list[Any] = []

    def cursor(self, **_: Any) -> FakeCursor:
        return FakeCursor(self.rows)

    async def execute(self, statement: Any, params: Any = None) -> None:
        self.statements.append(params)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return


class FakePublisher:
    def __init__(self, error: PublishError | None = None) -> None:
        self.error = error
        self.published: list[tuple[str, bytes, str]] = []

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.error is not None:
            raise self.error
        self.published.append((subject, payload, message_id))


def outbox_row(sequence: int) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "message_id": f"message-{sequence}",
        "subject": "test.subject",
        "payload": {},
        "traceparent": None,
    }


@pytest.fixture
def settings() -> DatabaseSettings:
    return DatabaseSettings(host="localhost", port=5432, name="test", user="test")


def patch_connection(monkeypatch: pytest.MonkeyPatch, connection: FakeConnection) -> list[int]:
    attempts: list[int] = []

    async def connect(*_: Any, **__: Any) -> FakeConnection:
        attempts.append(1)
        return connection

    monkeypatch.setattr(module.psycopg.AsyncConnection, "connect", connect)
    return attempts


def patch_envelope(monkeypatch: pytest.MonkeyPatch) -> None:

    def envelope(payload: dict[str, Any], published_at: datetime) -> bytes:
        return b"envelope"

    monkeypatch.setattr(module, "publication_envelope", envelope)


async def test_the_active_instance_publishes_until_asked_to_stop(
    settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = asyncio.Event()
    patch_connection(monkeypatch, FakeConnection())
    cycles: list[int] = []

    async def acquire(*_: Any) -> bool:
        return True

    async def holds(*_: Any) -> bool:
        return True

    async def pending(*_: Any) -> PublicationResult:
        cycles.append(1)
        if len(cycles) == 2:
            stop.set()
        return PublicationResult(published=1, failed=False)

    monkeypatch.setattr(module, "try_acquire_lock", acquire)
    monkeypatch.setattr(module, "holds_lock", holds)
    monkeypatch.setattr(module, "publish_pending", pending)
    beats: list[int] = []
    outbox = OutboxPublisher(settings, FakePublisher(), on_cycle=lambda: beats.append(1))

    await outbox.run(stop)

    assert len(cycles) == 2
    assert beats
    assert outbox.blocked_by_permanent_failure is False


async def test_an_instance_without_the_lock_keeps_waiting_and_beating(
    settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = asyncio.Event()
    patch_connection(monkeypatch, FakeConnection())

    async def acquire(*_: Any) -> bool:
        return False

    monkeypatch.setattr(module, "try_acquire_lock", acquire)
    beats: list[int] = []

    def beat() -> None:
        beats.append(1)
        stop.set()

    await OutboxPublisher(settings, FakePublisher(), on_cycle=beat).run(stop)

    assert beats == [1]


async def test_losing_the_lock_reconnects_to_compete_again(
    settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = asyncio.Event()
    attempts = patch_connection(monkeypatch, FakeConnection())
    lost: list[int] = []

    async def acquire(*_: Any) -> bool:
        return True

    async def holds(*_: Any) -> bool:
        lost.append(1)
        if len(lost) == 2:
            stop.set()
        return False

    monkeypatch.setattr(module, "try_acquire_lock", acquire)
    monkeypatch.setattr(module, "holds_lock", holds)

    await OutboxPublisher(settings, FakePublisher()).run(stop)

    assert len(attempts) == 2


async def test_a_connection_failure_is_logged_and_retried_with_backoff(
    settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()

    async def connect(*_: Any, **__: Any) -> FakeConnection:
        stop.set()  # o backoff termina na hora, porque a parada já foi pedida
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(module.psycopg.AsyncConnection, "connect", connect)

    with caplog.at_level(logging.WARNING, logger=module.logger.name):
        await OutboxPublisher(settings, FakePublisher()).run(stop)

    assert [r.getMessage() for r in caplog.records] == ["publisher connection lost"]


@pytest.mark.parametrize(
    ("result", "blocked"),
    [
        (PublicationResult(published=0, failed=True, permanent_failure=True), True),
        (PublicationResult(published=0, failed=True), False),
        (PublicationResult(published=0, failed=False), False),
    ],
)
async def test_the_result_of_a_batch_decides_the_readiness_and_the_wait(
    settings: DatabaseSettings,
    monkeypatch: pytest.MonkeyPatch,
    result: PublicationResult,
    blocked: bool,
) -> None:
    stop = asyncio.Event()
    patch_connection(monkeypatch, FakeConnection())

    async def acquire(*_: Any) -> bool:
        return True

    async def holds(*_: Any) -> bool:
        return True

    async def pending(*_: Any) -> PublicationResult:
        stop.set()  # a espera seguinte (backoff ou intervalo) termina na hora
        return result

    monkeypatch.setattr(module, "try_acquire_lock", acquire)
    monkeypatch.setattr(module, "holds_lock", holds)
    monkeypatch.setattr(module, "publish_pending", pending)
    outbox = OutboxPublisher(settings, FakePublisher())

    await outbox.run(stop)

    assert outbox.blocked_by_permanent_failure is blocked


async def test_a_confirmed_message_is_marked_as_published(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_envelope(monkeypatch)
    connection = FakeConnection([outbox_row(1), outbox_row(2)])
    publisher = FakePublisher()

    result = await publish_pending(cast(Any, connection), publisher, clock=lambda: NOW)

    assert result == PublicationResult(published=2, failed=False)
    assert [message_id for _, _, message_id in publisher.published] == ["message-1", "message-2"]
    assert connection.statements == [(1,), (2,)]


async def test_a_batch_over_its_time_budget_stops_before_the_next_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_envelope(monkeypatch)
    connection = FakeConnection([outbox_row(1)])
    ticks = iter([0.0, 100.0])

    result = await publish_pending(
        cast(Any, connection),
        FakePublisher(),
        maximum_seconds=10.0,
        clock=lambda: NOW,
        monotonic=lambda: next(ticks),
    )

    assert result == PublicationResult(published=0, failed=False)
    assert connection.statements == []


@pytest.mark.parametrize("permanent", [False, True])
async def test_a_transport_refusal_interrupts_the_batch_without_marking_the_message(
    monkeypatch: pytest.MonkeyPatch, permanent: bool
) -> None:
    patch_envelope(monkeypatch)
    connection = FakeConnection([outbox_row(1), outbox_row(2)])
    publisher = FakePublisher(PublishError("refused", permanent=permanent))

    result = await publish_pending(cast(Any, connection), publisher, clock=lambda: NOW)

    assert result == PublicationResult(published=0, failed=True, permanent_failure=permanent)
    assert connection.statements == []


async def test_a_message_outside_the_envelope_is_a_permanent_failure() -> None:
    connection = FakeConnection([outbox_row(1)])

    result = await publish_pending(cast(Any, connection), FakePublisher(), clock=lambda: NOW)

    assert result == PublicationResult(published=0, failed=True, permanent_failure=True)
    assert connection.statements == []
