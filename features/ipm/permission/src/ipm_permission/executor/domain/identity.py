"""Modelos de domínio do provedor de identidade (Zitadel) vistos pelo Executor."""

from dataclasses import dataclass


class ProviderError(Exception):
    """Falha ao escrever ou ler no Zitadel."""

    def __init__(self, reason: str, *, retryable: bool, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class IdentityProjectRole:
    """Role de projeto em `roles-<módulo>` no Zitadel (API v2)."""

    key: str
    display_name: str
    group: str
