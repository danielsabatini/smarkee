"""Portas e erros comuns aos papéis (sem I/O, podem ser usados pelo `domain/`)."""

from typing import Protocol


class PublishError(Exception):
    """O transporte recusou ou não confirmou a publicação.

    É uma falha repetível: quem publicou tenta de novo (o Receiver devolve ao cliente, os demais
    papéis refazem na rodada seguinte ou devolvem a mensagem à fila). `permanent` indica uma recusa
    que repetir não resolve (mensagem grande demais ou inválida); só o Publisher a trata à parte
    (decisão 0018).
    """

    def __init__(self, reason: str, *, permanent: bool = False) -> None:
        super().__init__(reason)
        self.permanent = permanent


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Publica e aguarda a confirmação do transporte.

        `message_id` é a chave de deduplicação do transporte (`Nats-Msg-Id`).
        """
        ...
