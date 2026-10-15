"""Conexão com o NATS JetStream e publicação das `action` pelo Reconciler (`docs/NATS.md`)."""

from typing import Any

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import SecretStr

from sum_service_reconciler.engine.reconciler import PublishError

PUBLISH_TIMEOUT_SECONDS = 5.0
_PERMANENT_ERRORS = (nats.errors.MaxPayloadError, nats.js.errors.BadRequestError)


async def connect(
    url: str, user: str, password: SecretStr | None, *, name: str = "sum-service-reconciler"
) -> NatsClient:
    """Conecta com a identidade do Reconciler (`sum-service-reconciler`)."""
    secret = password.get_secret_value() if password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    options: dict[str, Any] = {"servers": [url], "user": user, "password": secret, "name": name}
    return await nats.connect(**options)  # pyright: ignore[reportUnknownMemberType]


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica uma `action` e espera a confirmação, com `Nats-Msg-Id` igual ao `actionId`."""

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
            raise PublishError(type(error).__name__) from error
