"""O Receiver publica o `requested` e traduz a recusa do transporte em 503 repetível."""

from typing import Any, cast

import nats.errors
import pytest
from nats.js import JetStreamContext

from sum_service.receiver.domain.errors import ApiError
from sum_service.receiver.transport.nats import RequestedPublisher


class FakeJetStream:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.published: list[tuple[str, bytes, dict[str, Any]]] = []

    async def publish(self, subject: str, payload: bytes, **options: Any) -> None:
        if self.error is not None:
            raise self.error
        self.published.append((subject, payload, options))


async def test_the_request_is_published_with_the_operation_id_as_the_message_id() -> None:
    jetstream = FakeJetStream()
    await RequestedPublisher(cast(JetStreamContext, jetstream)).publish(
        "receiver.requested.sum.service.r-1.create", b"{}", message_id="op-1"
    )
    ((subject, payload, options),) = jetstream.published
    assert (subject, payload) == ("receiver.requested.sum.service.r-1.create", b"{}")
    assert options["headers"]["Nats-Msg-Id"] == "op-1"


@pytest.mark.parametrize("error", [TimeoutError(), OSError(), nats.errors.NoServersError()])
async def test_a_refusal_of_the_transport_becomes_a_retryable_503(error: Exception) -> None:
    publisher = RequestedPublisher(cast(JetStreamContext, FakeJetStream(error)))
    with pytest.raises(ApiError) as raised:
        await publisher.publish("s", b"{}", message_id="op-1")
    assert raised.value.status == 503
