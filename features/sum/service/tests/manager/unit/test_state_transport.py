"""Transporte de estado do Manager: leitura de `observed` e resultados, tentativas e desfechos."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import psycopg
import pytest
from nats.aio.msg import Msg

from sum_service.manager.domain.errors import PermanentMessageError
from sum_service.manager.transport import state
from sum_service.manager.transport.requested import Disposition
from sum_service.manager.transport.state import (
    REDELIVERY_DELAY_SECONDS,
    parse_observed,
    parse_result,
    process_observed,
    process_result,
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
        "data": {"serviceRoles": ["ipm.organization.get", "ipm.organization.list"]},
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


def test_an_observed_gives_the_resource_the_presence_and_the_roles_read() -> None:
    message = parse_observed(observed())
    assert message.resource_id == RESOURCE_ID
    assert message.presence == "present"
    assert message.service_roles == ("ipm.organization.get", "ipm.organization.list")


def test_an_observed_without_roles_has_none() -> None:
    assert parse_observed(observed(data={})).service_roles == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"presence": None},
        {"observedAt": None},
        {"data": {"serviceRoles": "não é lista"}},
        {"messageType": "completed"},
        {"module": "core"},
        {"schemaVersion": "2.0"},
    ],
)
def test_an_invalid_observed_is_permanently_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(PermanentMessageError):
        parse_observed(json.dumps({**json.loads(observed()), **changes}).encode())


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_a_result_gives_the_action_and_the_generation(outcome: str) -> None:
    message = parse_result(result(outcome), outcome)
    assert (message.action_id, message.desired_generation, message.outcome) == (
        f"{RESOURCE_ID}.1.update.observed",
        1,
        outcome,
    )


def test_a_result_without_action_or_generation_is_permanently_rejected() -> None:
    with pytest.raises(PermanentMessageError):
        parse_result(result(actionId=None), "completed")
    with pytest.raises(PermanentMessageError):
        parse_result(result(desiredGeneration=None), "completed")


def test_a_result_of_the_other_outcome_is_permanently_rejected() -> None:
    with pytest.raises(PermanentMessageError):
        parse_result(result("failed"), "completed")


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


async def test_a_valid_message_is_applied_and_acked(monkeypatch: pytest.MonkeyPatch) -> None:
    applied: list[str] = []

    async def apply_observed(connection: Any, message: Any) -> str:
        applied.append(message.resource_id)
        return "applied"

    monkeypatch.setattr(state, "apply_observed", apply_observed)
    assert await process_observed(cast(Any, FakePool()), observed()) is Disposition.ACK
    assert applied == [RESOURCE_ID]


async def test_a_permanently_invalid_message_is_terminated_without_touching_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    touched = False

    async def apply_result(connection: Any, message: Any) -> None:
        nonlocal touched
        touched = True

    monkeypatch.setattr(state, "apply_result", apply_result)
    assert await process_result(cast(Any, FakePool()), b"x", "completed") is Disposition.TERM
    assert not touched


async def test_a_transient_database_error_is_retried_in_place_and_then_acked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def apply_observed(connection: Any, message: Any) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise psycopg.errors.DeadlockDetected("deadlock")
        return "applied"

    monkeypatch.setattr(state, "apply_observed", apply_observed)
    assert await process_observed(cast(Any, FakePool()), observed()) is Disposition.ACK
    assert calls == 3


async def test_a_persistent_transient_error_goes_back_to_the_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def apply_observed(connection: Any, message: Any) -> str:
        nonlocal calls
        calls += 1
        raise psycopg.errors.LockNotAvailable("lock_timeout")

    monkeypatch.setattr(state, "apply_observed", apply_observed)
    assert await process_observed(cast(Any, FakePool()), observed()) is Disposition.RETRY
    assert calls == 4  # três esperas e a tentativa final


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
