"""Conexão com o NATS JetStream (`docs/NATS.md`)."""

import nats
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext

from core_account.publisher.settings import NatsSettings


async def connect(settings: NatsSettings, *, name: str = "core-account-publisher") -> NatsClient:
    """Conecta com a identidade do Publisher (`core-account-publisher`)."""
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]
