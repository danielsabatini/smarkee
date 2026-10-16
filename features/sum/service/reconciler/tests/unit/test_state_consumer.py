"""Consumer de estado da instância: nome único, `LAST_PER_SUBJECT` e limiar de inatividade."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from sum_service_reconciler.transport.nats import STREAMS, StateConsumer, new_instance_name


@dataclass
class FakeMessage:
    data: bytes
    acked: bool = False
    nak_delay: float | None = None

    async def ack(self) -> None:
        self.acked = True

    async def nak(self, delay: float | None = None) -> None:
        self.nak_delay = delay


@dataclass
class FakeSubscription:
    batches: list[list[FakeMessage]]
    stop: asyncio.Event

    async def fetch(self, batch: int, timeout: float) -> list[FakeMessage]:
        if self.batches:
            return self.batches.pop(0)
        self.stop.set()
        raise TimeoutError


@dataclass
class FakeJetStream:
    stop: asyncio.Event
    batches: list[list[FakeMessage]] = field(default_factory=lambda: [])
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=lambda: [])

    async def pull_subscribe(self, subject: str, **options: Any) -> FakeSubscription:
        self.calls.append((subject, options))
        return FakeSubscription(self.batches, self.stop)


def consumer(jetstream: FakeJetStream, handle: Any, *, instance: str = "abc12345") -> StateConsumer:
    return StateConsumer(
        jetstream,  # pyright: ignore[reportArgumentType]
        handle,
        stream="DESIRED",
        filter_subject="manager.desired.sum.service.>",
        name_suffix="desired",
        instance=instance,
        inactive_threshold_seconds=300,
    )


async def test_the_instance_rebuilds_its_state_from_the_last_message_of_each_subject() -> None:
    stop = asyncio.Event()
    jetstream = FakeJetStream(stop)

    async def handle(data: bytes) -> object:
        return None

    await consumer(jetstream, handle).run(stop)

    ((subject, options),) = jetstream.calls
    config: ConsumerConfig = options["config"]
    assert subject == "manager.desired.sum.service.>"
    assert options["durable"] == "sum-service-reconciler-desired-abc12345"
    assert options["stream"] == "DESIRED"
    assert config.deliver_policy is DeliverPolicy.LAST_PER_SUBJECT
    assert config.ack_policy is AckPolicy.EXPLICIT
    assert config.inactive_threshold == 300.0


async def test_a_handled_message_is_acknowledged_and_a_failed_one_goes_back_to_the_queue() -> None:
    stop = asyncio.Event()
    good, bad = FakeMessage(b"ok"), FakeMessage(b"quebrada")
    jetstream = FakeJetStream(stop, [[good, bad]])

    async def handle(data: bytes) -> object:
        if data == b"quebrada":
            raise RuntimeError("falha no motor")
        return None

    await consumer(jetstream, handle).run(stop)

    assert good.acked is True
    assert bad.acked is False and bad.nak_delay is not None  # volta à fila, não derruba o laço


def test_each_execution_gets_its_own_consumer_name() -> None:
    names = {new_instance_name() for _ in range(50)}
    assert len(names) == 50
    assert all(len(name) == 8 for name in names)


@pytest.mark.parametrize(("stream", "subject", "suffix"), STREAMS)
def test_every_filter_is_scoped_to_the_sum_service_resource(
    stream: str, subject: str, suffix: str
) -> None:
    assert stream in {"DESIRED", "OBSERVED", "RESULT"}
    assert subject.endswith(".sum.service.>")
    assert suffix in {"desired", "observed", "result"}
