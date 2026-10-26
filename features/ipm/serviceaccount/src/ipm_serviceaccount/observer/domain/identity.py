"""Tipos do provedor de identidade que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A leitura falhou ou foi inconclusiva. Não carrega dados da máquina."""


@dataclass(frozen=True, slots=True)
class IdentityMachine:
    state: str
    access_token_type: str


@dataclass(frozen=True, slots=True)
class IdentityKey:
    """Chave da máquina no provedor: só identificador e vencimento, nunca material de chave."""

    key_id: str
    expires_at: str | None
