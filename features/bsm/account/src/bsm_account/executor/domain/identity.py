"""Tipos do provedor de estado que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A escrita no estado falhou. `reason` e `retryable` seguem o contrato `failed`."""

    def __init__(self, reason: str, *, retryable: bool, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class StoredAccount:
    display_name: str
    billing_currency: str
    billing_contacts: list[str]
    deletion_protection: bool = True
