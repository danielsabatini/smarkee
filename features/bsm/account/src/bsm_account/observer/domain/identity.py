"""Tipos do provedor de estado que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A leitura falhou ou foi inconclusiva. Não carrega dados sensíveis da conta."""


@dataclass(frozen=True, slots=True)
class StoredAccount:
    display_name: str
    billing_currency: str
    billing_contacts: list[str]
    deletion_protection: bool | None = None
