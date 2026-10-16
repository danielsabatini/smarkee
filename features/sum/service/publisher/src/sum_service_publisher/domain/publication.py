"""Tipos puros da publicação do outbox (sem I/O)."""

from dataclasses import dataclass


class PublishError(Exception):
    """O transporte recusou ou não confirmou a publicação.

    `permanent` indica uma recusa que repetir não resolve (mensagem grande demais ou inválida).
    Ambas mantêm a mensagem pendente no outbox, para preservar a ordem; a permanente exige
    atuação humana e deixa o Publisher fora de `ready` (decisão 0018).
    """

    def __init__(self, reason: str, *, permanent: bool = False) -> None:
        super().__init__(reason)
        self.permanent = permanent


class PublicationRejectedError(Exception):
    """Uma mensagem do outbox não atende ao envelope. É uma falha permanente da mensagem."""


@dataclass(frozen=True, slots=True)
class PublicationResult:
    published: int
    failed: bool
    permanent_failure: bool = False
    """Recusa que repetir não resolve: o Publisher segue bloqueado até haver atuação humana."""
