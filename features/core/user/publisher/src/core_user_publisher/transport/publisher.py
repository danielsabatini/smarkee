"""Publicação no NATS JetStream pelo Publisher (`docs/NATS.md`).

Publicação com `Nats-Msg-Id` igual ao `messageId` e espera da confirmação do servidor. O
Publisher só
publica (no emissor `manager`); nunca consome.
"""

import nats.errors
import nats.js.errors
from nats.js import JetStreamContext

from core_user_publisher.domain.publication import PublishError

PUBLISH_TIMEOUT_SECONDS = 5.0

# Recusas que repetir não resolve: a mensagem nunca será aceita como está.
_PERMANENT_ERRORS = (nats.errors.MaxPayloadError, nats.js.errors.BadRequestError)


class JetStreamPublisher:
    """Publica no JetStream e espera a confirmação, com deduplicação pelo `messageId`."""

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        try:
            await self._jetstream.publish(
                subject,
                payload,
                timeout=PUBLISH_TIMEOUT_SECONDS,
                headers={"Nats-Msg-Id": message_id},
            )
        except (nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError) as error:
            raise PublishError(
                type(error).__name__, permanent=isinstance(error, _PERMANENT_ERRORS)
            ) from error
