"""Conexão com o NATS JetStream (`docs/NATS.md`)."""

from typing import Any

import nats
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import SecretStr


async def connect(
    url: str, user: str, password: SecretStr | None, *, name: str = "sum-service-publisher"
) -> NatsClient:
    """Conecta com a identidade do Publisher (`sum-service-publisher`)."""
    secret = password.get_secret_value() if password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    options: dict[str, Any] = {"servers": [url], "user": user, "password": secret, "name": name}
    return await nats.connect(**options)  # pyright: ignore[reportUnknownMemberType]


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]
