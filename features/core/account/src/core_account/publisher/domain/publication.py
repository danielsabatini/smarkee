"""Tipos puros da publicação do outbox (sem I/O)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicationResult:
    published: int
    failed: bool
    permanent_failure: bool = False
    """Recusa que repetir não resolve: o Publisher segue bloqueado até haver atuação humana."""
