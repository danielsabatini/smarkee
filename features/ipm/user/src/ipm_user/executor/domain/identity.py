"""Tipos do provedor de identidade que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A chamada ao Zitadel falhou. `reason` e `retryable` seguem o contrato `failed`."""

    def __init__(self, reason: str, *, retryable: bool, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class IdentityUser:
    email: str
    organization_id: str
    """Organização do provedor dona do usuário (`resourceOwner`)."""


@dataclass(frozen=True, slots=True)
class Authorization:
    """Autorização do usuário no projeto `roles-ipm`, na organização dele (uma só)."""

    authorization_id: str
    permissions: frozenset[str]
