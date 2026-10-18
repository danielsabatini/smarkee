"""Publicação no JetStream com deduplicação pelo `messageId` (`docs/NATS.md`)."""

import nats.errors
import nats.js.errors
from nats.js import JetStreamContext

from sum_service_publisher.domain.publication import PublishError
from sum_service_publisher.logging_config import TRACEPARENT_HEADER, current_traceparent

PUBLISH_TIMEOUT_SECONDS = 5.0
_PERMANENT_ERRORS = (nats.errors.MaxPayloadError, nats.js.errors.BadRequestError)


class JetStreamPublisher:
    """Publica no JetStream e espera a confirmação, com `Nats-Msg-Id` igual ao `messageId`."""

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        headers = {"Nats-Msg-Id": message_id}
        traceparent = current_traceparent()
        if traceparent is not None:
            headers[TRACEPARENT_HEADER] = traceparent
        try:
            await self._jetstream.publish(
                subject, payload, timeout=PUBLISH_TIMEOUT_SECONDS, headers=headers
            )
        except (nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError) as error:
            raise PublishError(
                type(error).__name__, permanent=isinstance(error, _PERMANENT_ERRORS)
            ) from error
