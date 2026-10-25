"""Tipos do provedor de estado que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A leitura falhou ou foi inconclusiva. Não carrega dados sensíveis da Role."""


@dataclass(frozen=True, slots=True)
class StoredRole:
    name: str
    description: str
    permissions: list[str]
    deletion_protection: bool | None = None
