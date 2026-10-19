"""Tipos do provedor de identidade que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A leitura falhou ou foi inconclusiva. Não carrega dados do usuário."""


@dataclass(frozen=True, slots=True)
class ZitadelUser:
    state: str
    email_verified: bool
    password_set: bool
