"""Tipos do provedor de estado que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A leitura falhou ou foi inconclusiva. Não carrega dados sensíveis do Grupo."""


@dataclass(frozen=True, slots=True)
class StoredGroup:
    organization_id: str
    name: str
    description: str
    roles: list[str]
    deletion_protection: bool | None = None
