"""Transporte de estado do Manager: tentativas e desfechos de `observed` e resultados.

A leitura do envelope e a decisão são dos handlers do template (decisão 0080), testadas em
`test_convergence.py` e na integração.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import psycopg
import pytest
from nats.aio.msg import Msg

from sum_service.manager.domain.errors import PermanentMessageError
from sum_service.manager.domain.outcome import Outcome, OutcomeKind
from sum_service.manager.transport import state
from sum_service.manager.transport.requested import Disposition
from sum_service.manager.transport.state import (
    REDELIVERY_DELAY_SECONDS,
    process_state,
)

RESOURCE_ID = "01a14168-b59d-7475-8db7-c5cf57fa100b"


def envelope(message_type: str, emitter: str, **changes: Any) -> bytes:
    message: dict[str, Any] = {
        "messageId": "01a14168-b59d-7475-8db7-c5cf57fa1001",
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": emitter,
        "module": "sum",
        "resourceType": "service",
        "resourceId": RESOURCE_ID,
        "operation": "changed",
        "correlationId": "01a14168-b59d-7475-8db7-c5cf57fa1002",
        "occurredAt": "2026-10-16T10:00:00+00:00",
        "publishedAt": "2026-10-16T10:00:01+00:00",
        "data": {},
    }
    message.update(changes)
    return json.dumps(message).encode()


def observed(**changes: Any) -> bytes:
    fields: dict[str, Any] = {
        "presence": "present",
        "observedAt": "2026-10-16T10:00:00+00:00",
        "data": {"servicePermissions": ["ipm.organization.get", "ipm.organization.list"]},
    }
    fields.update(changes)
    return envelope("observed", "observer", **fields)


def result(outcome: str = "completed", **changes: Any) -> bytes:
    fields: dict[str, Any] = {
        "actionId": f"{RESOURCE_ID}.1.update.observed",
        "desiredGeneration": 1,
        "operation": "update",
    }
    fields.update(changes)
    return envelope(outcome, "executor", **fields)


# ---------------------------------------------------------------- tentativas e desfechos


class FakeConnection:
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        yield


class FakePool:
    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[FakeConnection]:
        yield FakeConnection()


async def fast_sleep(delay: float) -> None: ...


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state.asyncio, "sleep", fast_sleep)


@dataclass
class FakeHandler:
    """Faz o papel do handler do template: falha com os erros dados e depois aplica."""

    errors: list[Exception] = field(default_factory=lambda: [])
    applied: list[str] = field(default_factory=lambda: [])

    async def handle(self, store: Any, kind: Any, raw_message: Mapping[str, Any]) -> Outcome:
        if self.errors:
            raise self.errors.pop(0)
        self.applied.append(str(raw_message["resourceId"]))
        return Outcome(OutcomeKind.APPLIED)


async def test_a_valid_message_is_applied_and_acked() -> None:
    handler = FakeHandler()
    assert await process_state(cast(Any, FakePool()), handler, observed()) is Disposition.ACK
    assert handler.applied == [RESOURCE_ID]


async def test_a_message_that_is_not_json_is_terminated_without_touching_the_database() -> None:
    handler = FakeHandler()
    assert await process_state(cast(Any, FakePool()), handler, b"x") is Disposition.TERM
    assert handler.applied == []


async def test_a_permanently_invalid_message_is_terminated() -> None:
    handler = FakeHandler(errors=[PermanentMessageError("fora do contrato")])
    assert await process_state(cast(Any, FakePool()), handler, result()) is Disposition.TERM
    assert handler.applied == []


async def test_a_transient_database_error_is_retried_in_place_and_then_acked() -> None:
    deadlock = psycopg.errors.DeadlockDetected("deadlock")
    handler = FakeHandler(errors=[deadlock, deadlock])
    assert await process_state(cast(Any, FakePool()), handler, observed()) is Disposition.ACK
    assert handler.applied == [RESOURCE_ID]


async def test_a_persistent_transient_error_goes_back_to_the_queue() -> None:
    handler = FakeHandler(errors=[psycopg.errors.LockNotAvailable("lock_timeout")] * 5)
    assert await process_state(cast(Any, FakePool()), handler, observed()) is Disposition.RETRY
    assert len(handler.errors) == 1  # três esperas e a tentativa final


@dataclass
class FakeMessage:
    data: bytes = b"{}"
    headers: dict[str, str] | None = None
    settled: list[str] = field(default_factory=lambda: [])

    async def ack(self) -> None:
        self.settled.append("ack")

    async def term(self) -> None:
        self.settled.append("term")

    async def nak(self, delay: float | None = None) -> None:
        self.settled.append(f"nak:{delay}")


@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        (Disposition.ACK, "ack"),
        (Disposition.TERM, "term"),
        (Disposition.RETRY, f"nak:{REDELIVERY_DELAY_SECONDS}"),
    ],
)
async def test_each_disposition_settles_the_message_in_the_transport(
    disposition: Disposition, expected: str
) -> None:
    async def handle(data: bytes) -> Disposition:
        return disposition

    message = FakeMessage()
    await state._settle(cast(Msg, message), handle)  # pyright: ignore[reportPrivateUsage]
    assert message.settled == [expected]


@dataclass
class FakeSubscription:
    stop: asyncio.Event
    batches: list[list[FakeMessage]]
    unsubscribed: bool = False

    async def fetch(self, batch: int, timeout: float) -> list[Msg]:
        if self.batches:
            return [cast(Msg, message) for message in self.batches.pop(0)]
        self.stop.set()
        raise TimeoutError

    async def unsubscribe(self) -> None:
        self.unsubscribed = True


class FakeStream:
    def __init__(self, subscription: FakeSubscription) -> None:
        self.subscription = subscription
        self.bound: dict[str, Any] = {}

    async def pull_subscribe_bind(self, **options: Any) -> FakeSubscription:
        self.bound = options
        return self.subscription


async def test_the_consumer_loop_binds_to_the_durable_and_settles_every_message() -> None:
    stop = asyncio.Event()
    first, second = FakeMessage(b"1"), FakeMessage(b"2")
    subscription = FakeSubscription(stop, [[first, second]])
    jetstream = FakeStream(subscription)

    async def handle(data: bytes) -> Disposition:
        return Disposition.TERM if data == b"2" else Disposition.ACK

    await state.run_consumer(
        cast(Any, jetstream), stream="OBSERVED", durable="d-observed", handle=handle, stop=stop
    )

    assert jetstream.bound == {"consumer": "d-observed", "stream": "OBSERVED"}
    assert (first.settled, second.settled) == (["ack"], ["term"])
    assert subscription.unsubscribed
