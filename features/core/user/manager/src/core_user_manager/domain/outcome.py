"""Resultado do tratamento de um `requested` pelo Manager."""

from dataclasses import dataclass
from enum import StrEnum


class OutcomeKind(StrEnum):
    ACCEPTED = "accepted"
    """Pedido aplicado; a Operation aguarda a convergência."""

    COMPLETED = "completed"
    """Pedido aplicado sem nada a convergir (nenhuma mudança efetiva)."""

    REJECTED = "rejected"
    """Pedido não aplicado; o recurso não foi alterado (`SSOT.md` §10.1)."""

    DUPLICATE = "duplicate"
    """Reentrega ou repetição do cliente: nada foi gravado."""

    APPLIED = "applied"
    """`observed` ou resultado de ação aplicado ao recurso."""

    IGNORED = "ignored"
    """Descartada sem efeito: recurso inexistente, observação antiga ou geração obsoleta."""


class RejectionReason(StrEnum):
    """Motivos de rejeição de uma Operation (`SSOT.md`, Operation)."""

    CONFLICT = "conflict"
    VALIDATION = "validation"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    reason: RejectionReason | None = None
    digest_mismatch: bool = False
    """Reentrega com `requestDigest` diferente: sinal de observabilidade.

    A Operation original prevalece.
    """
