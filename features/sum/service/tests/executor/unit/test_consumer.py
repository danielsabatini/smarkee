"""Consumer do Executor e leitura direta do estado: desfechos e ausência (`docs/NATS.md` §7.3)."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, cast

import nats.js.errors
import pytest
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from sum_service.common.messaging import REDELIVERY_DELAY_SECONDS
from sum_service.executor.transport.consumers import PullConsumer
from sum_service.executor.transport.messaging import DirectStateReader


@dataclass
class FakeMessage:
    data: bytes = b"{}"
    headers: dict[str, str] | None = None
    settled: list[str] = field(default_factory=lambda: [])

    async def ack(self) -> None:
        self.settled.append("ack")

    async def nak(self, delay: float | None = None) -> None:
        self.settled.append(f"nak:{delay}")


def consumer(handle: Any) -> PullConsumer:
    return PullConsumer(cast(JetStreamContext, None), stream="ACTION", durable="d", handle=handle)


async def settle(handle: Any) -> list[str]:
    message = FakeMessage()
    await consumer(handle)._settle(cast(Msg, message))  # pyright: ignore[reportPrivateUsage]
    return message.settled


async def test_a_handled_action_is_acked() -> None:
    async def handle(data: bytes) -> object:
        return None

    assert await settle(handle) == ["ack"]


async def test_a_failed_action_returns_to_the_queue_with_a_delay_and_does_not_stop_the_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handle(data: bytes) -> object:
        raise RuntimeError("falha no motor")

    assert await settle(handle) == [f"nak:{REDELIVERY_DELAY_SECONDS}"]
    assert any(r.getMessage().startswith("message processing failed") for r in caplog.records)


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


async def test_the_consumer_binds_to_the_declared_durable_and_settles_each_message() -> None:
    stop = asyncio.Event()
    message = FakeMessage()
    subscription = FakeSubscription(stop, [[message]])
    jetstream = FakeStream(subscription)
    handled: list[bytes] = []

    async def handle(data: bytes) -> object:
        handled.append(data)

    await PullConsumer(
        cast(JetStreamContext, jetstream),
        stream="ACTION",
        durable="sum-service-executor-action-p1",
        handle=handle,
    ).run(stop)

    assert jetstream.bound == {"consumer": "sum-service-executor-action-p1", "stream": "ACTION"}
    assert handled == [b"{}"]
    assert message.settled == ["ack"]
    assert subscription.unsubscribed  # o drain da conexão não espera o tempo limite


@dataclass
class FakeStored:
    data: bytes | None


class FakeStateStream:
    def __init__(self, stored: dict[tuple[str, str], FakeStored]) -> None:
        self.stored = stored

    async def get_last_msg(self, stream: str, subject: str) -> FakeStored:
        try:
            return self.stored[(stream, subject)]
        except KeyError:
            raise nats.js.errors.NotFoundError from None


async def test_the_last_desired_and_the_last_result_are_read_from_their_subjects() -> None:
    jetstream = FakeStateStream(
        {
            ("DESIRED", "manager.desired.sum.service.r-1.changed"): FakeStored(b'{"d": 1}'),
            ("RESULT", "executor.completed.sum.service.r-1"): FakeStored(b'{"r": 1}'),
        }
    )
    reader = DirectStateReader(cast(JetStreamContext, jetstream))
    assert await reader.last_desired("r-1") == b'{"d": 1}'
    assert await reader.last_result("r-1", "completed") == b'{"r": 1}'


async def test_a_subject_without_message_reads_as_absent_and_an_empty_payload_as_empty_bytes() -> (
    None
):
    jetstream = FakeStateStream({("RESULT", "executor.failed.sum.service.r-2"): FakeStored(None)})
    reader = DirectStateReader(cast(JetStreamContext, jetstream))
    assert await reader.last_desired("r-2") is None
    assert await reader.last_result("r-2", "failed") == b""
