"""O `JetStreamPublisher` repassa o `traceparent` do contexto como header NATS (decisão 0055)."""

from typing import Any, cast

from nats.js import JetStreamContext

from ipm_organization_executor.logging_config import bind_traceparent
from ipm_organization_executor.transport.nats import JetStreamPublisher

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class FakeJetStream:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    async def publish(self, subject: str, payload: bytes, **options: Any) -> None:
        self.headers.append(options["headers"])


async def publish_with(traceparent: str | None) -> dict[str, str]:
    jetstream = FakeJetStream()
    bind_traceparent(traceparent)
    try:
        await JetStreamPublisher(cast(JetStreamContext, jetstream)).publish(
            "s", b"{}", message_id="m-1"
        )
    finally:
        bind_traceparent(None)
    return jetstream.headers[0]


async def test_traceparent_is_forwarded_unchanged_next_to_the_message_id() -> None:
    assert await publish_with(TRACEPARENT) == {"Nats-Msg-Id": "m-1", "traceparent": TRACEPARENT}


async def test_without_context_only_the_message_id_is_sent() -> None:
    assert await publish_with(None) == {"Nats-Msg-Id": "m-1"}
