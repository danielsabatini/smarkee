"""Tipos do provedor de identidade que o domínio conhece (sem I/O)."""

from dataclasses import dataclass


class ProviderError(Exception):
    """A leitura falhou ou foi inconclusiva. Não carrega dados da organização."""


@dataclass(frozen=True, slots=True)
class ZitadelOrganization:
    name: str
    state: str
    """Estado como o Zitadel informa (por exemplo, `ORGANIZATION_STATE_ACTIVE`)."""
