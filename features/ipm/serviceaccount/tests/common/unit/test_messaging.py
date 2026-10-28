"""Adaptadores comuns do NATS: publicação, escopo de trace da mensagem e laço de consumo."""

import asyncio
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import nats.errors
import pytest
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy

from ipm_serviceaccount.common import messaging
from ipm_serviceaccount.common.logging_config import bind_traceparent, current_traceparent
from ipm_serviceaccount.common.messaging import (
    StateConsumer,
    StreamPublisher,
    consume,
    message_scope,
    new_instance_name,
)
from ipm_serviceaccount.common.ports import PublishError
from ipm_serviceaccount.common.settings import MessagingSettings

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


# ---------------------------------------------------------------- publicação


class FakeStream:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.headers: list[dict[str, str]] = []

    async def publish(self, subject: str, payload: bytes, **options: Any) -> None:
        if self.error is not None:
            raise self.error
        self.headers.append(options["headers"])


async def publish_with(traceparent: str | None) -> dict[str, str]:
    jetstream = FakeStream()
    bind_traceparent(traceparent)
    try:
        await StreamPublisher(cast(JetStreamContext, jetstream)).publish(
            "s", b"{}", message_id="m-1"
        )
    finally:
        bind_traceparent(None)
    return jetstream.headers[0]


async def test_traceparent_is_forwarded_unchanged_next_to_the_message_id() -> None:
    assert await publish_with(TRACEPARENT) == {"Nats-Msg-Id": "m-1", "traceparent": TRACEPARENT}


async def test_without_context_only_the_message_id_is_sent() -> None:
    assert await publish_with(None) == {"Nats-Msg-Id": "m-1"}


@pytest.mark.parametrize(
    ("error", "permanent"),
    [
        (TimeoutError(), False),
        (OSError(), False),
        (nats.errors.NoServersError(), False),
        (nats.errors.MaxPayloadError(), True),
    ],
)
async def test_a_refused_publication_becomes_a_publish_error(
    error: Exception, permanent: bool
) -> None:
    publisher = StreamPublisher(cast(JetStreamContext, FakeStream(error)))
    with pytest.raises(PublishError) as raised:
        await publisher.publish("s", b"{}", message_id="m-1")
    assert raised.value.permanent is permanent
    assert str(raised.value) == type(error).__name__


# ---------------------------------------------------------------- escopo da mensagem


@dataclass
class FakeMessage:
    headers: dict[str, str] | None = None
    data: bytes = b"{}"
    acked: bool = False
    naked_with_delay: float | None = None
    terminated: bool = False
    num_delivered: int = 1

    @property
    def metadata(self) -> Msg.Metadata:
        return cast(
            Msg.Metadata,
            SimpleNamespace(
                num_delivered=self.num_delivered, sequence=SimpleNamespace(stream=7, consumer=3)
            ),
        )

    async def ack(self) -> None:
        self.acked = True

    async def nak(self, delay: float | None = None) -> None:
        self.naked_with_delay = delay

    async def term(self) -> None:
        self.terminated = True


def as_msg(message: FakeMessage) -> Msg:
    return cast(Msg, message)


def test_the_header_traceparent_is_the_context_inside_the_scope_only() -> None:
    bind_traceparent(None)
    with message_scope(as_msg(FakeMessage({"traceparent": TRACEPARENT}))):
        assert current_traceparent() == TRACEPARENT
    assert current_traceparent() is None  # o contexto vale só para esta mensagem


@pytest.mark.parametrize("headers", [None, {}, {"traceparent": "garbage"}])
def test_a_missing_or_invalid_header_clears_a_previous_context(
    headers: dict[str, str] | None,
) -> None:
    bind_traceparent(TRACEPARENT)  # contexto da mensagem anterior não pode vazar
    with message_scope(as_msg(FakeMessage(headers))):
        assert current_traceparent() is None


def test_the_context_is_cleared_even_when_the_handler_fails() -> None:
    with (
        pytest.raises(RuntimeError),
        message_scope(as_msg(FakeMessage({"traceparent": TRACEPARENT}))),
    ):
        raise RuntimeError
    assert current_traceparent() is None


# ---------------------------------------------------------------- laço de consumo


@dataclass
class FakeSubscription:
    """Entrega lotes na ordem e, esgotados, pede a parada do laço."""

    stop: asyncio.Event
    batches: list[list[FakeMessage] | Exception]
    requested: list[tuple[int, float]] = field(default_factory=lambda: [])
    unsubscribed: bool = False
    unsubscribe_error: Exception | None = None

    async def unsubscribe(self) -> None:
        self.unsubscribed = True
        if self.unsubscribe_error is not None:
            raise self.unsubscribe_error

    async def fetch(self, batch: int, timeout: float) -> list[Msg]:
        self.requested.append((batch, timeout))
        if not self.batches:
            self.stop.set()
            raise TimeoutError
        item = self.batches.pop(0)
        if isinstance(item, Exception):
            raise item
        return [as_msg(message) for message in item]


async def run_consume(
    batches: list[list[FakeMessage] | Exception], *, with_trace: bool = True
) -> tuple[list[tuple[bytes, str | None]], int, FakeSubscription]:
    stop = asyncio.Event()
    subscription = FakeSubscription(stop, batches)
    settled: list[tuple[bytes, str | None]] = []
    cycles = 0

    async def settle(message: Msg) -> None:
        settled.append((message.data, current_traceparent()))
        await message.ack()

    def on_cycle() -> None:
        nonlocal cycles
        cycles += 1

    await consume(
        cast(JetStreamContext.PullSubscription, subscription),
        settle,
        stop,
        batch_size=7,
        fetch_timeout_seconds=0.5,
        on_cycle=on_cycle,
        with_trace=with_trace,
    )
    return settled, cycles, subscription


async def test_every_message_is_settled_in_order_with_the_trace_of_its_own_header() -> None:
    bind_traceparent(None)
    first = FakeMessage({"traceparent": TRACEPARENT}, b"1")
    second = FakeMessage(None, b"2")
    settled, cycles, subscription = await run_consume([[first, second]])
    assert settled == [(b"1", TRACEPARENT), (b"2", None)]
    assert first.acked and second.acked
    assert cycles == 2  # um por busca: o laço dá sinal de vida mesmo sem mensagens
    assert subscription.requested[0] == (7, 0.5)


async def test_without_trace_the_header_is_not_bound_to_the_logs() -> None:
    bind_traceparent(None)
    settled, _, _ = await run_consume(
        [[FakeMessage({"traceparent": TRACEPARENT}, b"1")]], with_trace=False
    )
    assert settled == [(b"1", None)]


async def test_a_failed_fetch_is_logged_and_the_loop_goes_on(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(messaging, "FETCH_ERROR_PAUSE_SECONDS", 0.0)
    message = FakeMessage(None, b"depois")
    with caplog.at_level(logging.WARNING, logger=messaging.logger.name):
        settled, _, _ = await run_consume([nats.errors.ConnectionClosedError(), [message]])
    assert [data for data, _ in settled] == [b"depois"]
    assert any(record.getMessage() == "fetch failed" for record in caplog.records)


# ---------------------------------------------------------------- consumer de estado


class FakeStateStream:
    def __init__(self, subscription: FakeSubscription) -> None:
        self.subscription = subscription
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def pull_subscribe(self, subject: str, **options: Any) -> FakeSubscription:
        self.calls.append((subject, options))
        return self.subscription


class RecordingSink:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_message(self, data: bytes) -> None:
        self.received.append(data)


@pytest.mark.parametrize("traced", [True, False])
async def test_the_state_consumer_replays_the_last_message_per_subject_and_acks(
    traced: bool, caplog: pytest.LogCaptureFixture
) -> None:
    stop = asyncio.Event()
    message = FakeMessage(None, b"estado")
    jetstream = FakeStateStream(FakeSubscription(stop, [[message]]))
    sink = RecordingSink()
    consumer = StateConsumer(
        cast(JetStreamContext, jetstream),
        sink,
        durable="ipm-serviceaccount-x-desired-abc",
        stream="DESIRED",
        filter_subject="desired.ipm.serviceaccount.>",
        inactive_threshold_seconds=300,
        traced=traced,
    )
    with caplog.at_level(logging.DEBUG, logger=messaging.logger.name):
        await consumer.run(stop)

    subject, options = jetstream.calls[0]
    config = cast(ConsumerConfig, options["config"])
    assert subject == "desired.ipm.serviceaccount.>"
    assert (options["durable"], options["stream"]) == ("ipm-serviceaccount-x-desired-abc", "DESIRED")
    assert config.deliver_policy is DeliverPolicy.LAST_PER_SUBJECT
    assert config.inactive_threshold == 300.0
    assert sink.received == [b"estado"]
    assert message.acked
    assert consumer.is_synced
    handled = [record for record in caplog.records if record.getMessage() == "message handled"]
    assert bool(handled) is traced


async def test_state_consumer_sync_status_with_consumer_info() -> None:
    @dataclass
    class FakeInfo:
        num_pending: int
        num_ack_pending: int = 0

    class SubscriptionWithInfo(FakeSubscription):
        def __init__(
            self, stop: asyncio.Event, batches: list[list[FakeMessage] | Exception]
        ) -> None:
            super().__init__(stop, batches)
            self._info_calls = 0

        async def consumer_info(self) -> FakeInfo:
            self._info_calls += 1
            # Na primeira chamada (partida), ainda há mensagens pendentes
            pending = 1 if self._info_calls == 1 else 0
            return FakeInfo(num_pending=pending, num_ack_pending=0)

    stop = asyncio.Event()
    message = FakeMessage(None, b"primeiro")
    subscription = SubscriptionWithInfo(stop, [[message]])
    jetstream = FakeStateStream(subscription)
    sink = RecordingSink()
    consumer = StateConsumer(
        cast(JetStreamContext, jetstream),
        sink,
        durable="sub-test",
        stream="DESIRED",
        filter_subject="test.>",
        inactive_threshold_seconds=300,
        traced=False,
    )
    assert not consumer.is_synced
    await consumer.run(stop)
    assert consumer.is_synced
    assert await consumer.wait_synced(timeout=0.1)


def test_each_process_run_gets_its_own_instance_name() -> None:
    first, second = new_instance_name(), new_instance_name()
    assert first != second
    assert len(first) == len(second) == 8


async def test_the_subscription_is_cancelled_when_the_loop_ends() -> None:
    _, _, subscription = await run_consume([[FakeMessage(None, b"1")]])
    assert subscription.unsubscribed


async def test_the_subscription_is_cancelled_even_when_a_message_handler_fails() -> None:
    stop = asyncio.Event()
    subscription = FakeSubscription(stop, [[FakeMessage(None, b"1")]])

    async def settle(message: Msg) -> None:
        raise RuntimeError

    with pytest.raises(RuntimeError):
        await consume(
            cast(JetStreamContext.PullSubscription, subscription), settle, stop, batch_size=1
        )
    assert subscription.unsubscribed


async def test_an_error_while_cancelling_the_subscription_does_not_hide_the_shutdown() -> None:
    stop = asyncio.Event()
    subscription = FakeSubscription(stop, [])
    subscription.unsubscribe_error = nats.errors.ConnectionClosedError()

    async def settle(message: Msg) -> None: ...

    await consume(cast(JetStreamContext.PullSubscription, subscription), settle, stop, batch_size=1)
    assert subscription.unsubscribed


class FailingSink:
    async def on_message(self, data: bytes) -> None:
        raise RuntimeError("falha de processamento")


async def test_a_processing_error_returns_the_message_to_the_queue_and_keeps_the_loop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()
    failing, healthy = FakeMessage(None, b"ruim"), FakeMessage(None, b"bom")
    jetstream = FakeStateStream(FakeSubscription(stop, [[failing, healthy]]))
    consumer = StateConsumer(
        cast(JetStreamContext, jetstream),
        FailingSink(),
        durable="ipm-serviceaccount-x-desired-abc",
        stream="DESIRED",
        filter_subject="desired.ipm.serviceaccount.>",
        inactive_threshold_seconds=300,
        traced=True,
    )
    with caplog.at_level(logging.ERROR, logger=messaging.logger.name):
        await consumer.run(stop)

    assert not failing.acked
    assert failing.naked_with_delay == messaging.REDELIVERY_DELAY_SECONDS
    assert healthy.naked_with_delay == messaging.REDELIVERY_DELAY_SECONDS  # o laço seguiu
    failed = [r for r in caplog.records if r.getMessage().startswith("message processing failed")]
    assert len(failed) == 2
    assert failed[0].exc_info is not None
    assert failed[0].exc_info[0] is RuntimeError


@pytest.mark.parametrize(
    ("delivery", "expected"),
    [(1, 5.0), (2, 10.0), (3, 20.0), (4, 40.0), (5, 60.0), (19, 60.0)],
)
def test_the_redelivery_delay_grows_up_to_a_limit(delivery: int, expected: float) -> None:
    assert messaging.redelivery_delay(delivery) == expected


async def test_a_message_that_keeps_failing_is_terminated_after_the_maximum_deliveries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()
    poison = FakeMessage(None, b"venenosa", num_delivered=messaging.MAXIMUM_DELIVERIES)
    retryable = FakeMessage(None, b"outra", num_delivered=messaging.MAXIMUM_DELIVERIES - 1)
    jetstream = FakeStateStream(FakeSubscription(stop, [[poison, retryable]]))
    consumer = StateConsumer(
        cast(JetStreamContext, jetstream),
        FailingSink(),
        durable="ipm-serviceaccount-x-desired-abc",
        stream="DESIRED",
        filter_subject="desired.ipm.serviceaccount.>",
        inactive_threshold_seconds=300,
        traced=True,
    )
    with caplog.at_level(logging.ERROR, logger=messaging.logger.name):
        await consumer.run(stop)

    assert poison.terminated
    assert not poison.acked
    assert poison.naked_with_delay is None
    assert not retryable.terminated  # ainda abaixo do limite: volta à fila
    assert retryable.naked_with_delay == messaging.MAXIMUM_REDELIVERY_DELAY_SECONDS
    assert any(r.getMessage().startswith("message discarded") for r in caplog.records)


async def test_the_state_consumer_limits_the_deliveries_of_each_message() -> None:
    stop = asyncio.Event()
    jetstream = FakeStateStream(FakeSubscription(stop, []))
    consumer = StateConsumer(
        cast(JetStreamContext, jetstream),
        FailingSink(),
        durable="ipm-serviceaccount-x-desired-abc",
        stream="DESIRED",
        filter_subject="desired.ipm.serviceaccount.>",
        inactive_threshold_seconds=300,
        traced=True,
    )
    await consumer.run(stop)
    config = cast(ConsumerConfig, jetstream.calls[0][1]["config"])
    assert config.max_deliver == messaging.MAXIMUM_DELIVERIES


async def test_connect_never_gives_up_reconnecting(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_connect(**options: Any) -> object:
        captured.update(options)
        return object()

    monkeypatch.setattr(messaging.nats, "connect", fake_connect)
    await messaging.connect(
        MessagingSettings(url="nats://localhost:4222", user="u"), name="x-manager"
    )
    assert captured["max_reconnect_attempts"] == -1
    assert captured["name"] == "x-manager"
    for callback in ("error_cb", "disconnected_cb", "reconnected_cb"):
        assert callable(captured[callback])


async def test_the_connection_callbacks_only_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=messaging.logger.name):
        await messaging._log_connection_error(OSError("recusada"))  # pyright: ignore[reportPrivateUsage]
        await messaging._log_disconnected()  # pyright: ignore[reportPrivateUsage]
        await messaging._log_reconnected()  # pyright: ignore[reportPrivateUsage]
    assert [r.getMessage() for r in caplog.records] == [
        "messaging connection error",
        "messaging connection lost; reconnecting",
        "messaging connection restored",
    ]


async def test_connect_refuses_to_guess_the_address_when_the_url_was_not_informed() -> None:
    with pytest.raises(ValueError, match=r"messaging\.url"):
        await messaging.connect(MessagingSettings(), name="x-manager")
