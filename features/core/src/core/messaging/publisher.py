"""Publicação no transporte: a API publica `requested`; o relay publica as mensagens do Manager."""

from typing import Protocol


class PublishError(Exception):
    """O transporte recusou ou não confirmou a publicação (indisponível, ou `REQUESTED` cheio).

    É uma rejeição repetível: o cliente pode tentar de novo (`docs/NATS.md` §6.3).
    """


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Publica e aguarda a confirmação do transporte.

        `message_id` é a chave de deduplicação do transporte (`Nats-Msg-Id`).
        """
        ...
