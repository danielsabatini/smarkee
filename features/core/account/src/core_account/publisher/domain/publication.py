"""Tipos puros da publicação do outbox (sem I/O)."""

from dataclasses import dataclass


class PublicationRejectedError(Exception):
    """Uma mensagem do outbox não atende ao envelope. É uma falha permanente da mensagem."""


@dataclass(frozen=True, slots=True)
class PublicationResult:
    published: int
    failed: bool
    permanent_failure: bool = False
    """Recusa que repetir não resolve: o Publisher segue bloqueado até haver atuação humana."""
