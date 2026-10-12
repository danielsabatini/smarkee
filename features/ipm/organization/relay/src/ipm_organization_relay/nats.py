"""Publicação no NATS JetStream do relay (`docs/NATS.md`).

Publicação com `Nats-Msg-Id` igual ao `messageId` e espera da confirmação do servidor. O relay só
publica (no emissor `manager`); nunca consome.
"""

from typing import Protocol

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext

from ipm_organization_relay.settings import NatsSettings

PUBLISH_TIMEOUT_SECONDS = 5.0


class PublishError(Exception):
    """O transporte recusou ou não confirmou a publicação (indisponível, ou Stream cheio).

    É uma falha repetível: o relay mantém a mensagem pendente e tenta de novo (`docs/POSTGRESQL.md`
    §11.5).
    """


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Publica e aguarda a confirmação do transporte.

        `message_id` é a chave de deduplicação do transporte (`Nats-Msg-Id`).
        """
        ...


async def connect(
    settings: NatsSettings, *, name: str = "srv-ipm-organization-relay"
) -> NatsClient:
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    """Contexto JetStream da conexão (o pyright não conhece as opções livres do nats-py)."""
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


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
            raise PublishError(type(error).__name__) from error
