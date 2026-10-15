"""Conexão e publicação do `requested` pelo Receiver (`docs/NATS.md`).

Publica com `Nats-Msg-Id` igual ao `operationId`: o transporte descarta a repetição do mesmo pedido.
"""

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import SecretStr

from sum_service_receiver.domain.errors import unavailable

PUBLISH_TIMEOUT_SECONDS = 5.0


async def connect(url: str, user: str, password: SecretStr | None) -> NatsClient:
    secret = password.get_secret_value() if password else None
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[url], user=user, password=secret, name="sum-service-receiver"
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class RequestedPublisher:
    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Recusa do transporte vira 503 com `Retry-After`: o cliente repete com a mesma chave."""
        try:
            await self._jetstream.publish(
                subject,
                payload,
                timeout=PUBLISH_TIMEOUT_SECONDS,
                headers={"Nats-Msg-Id": message_id},
            )
        except nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError:
            raise unavailable() from None
