"""Modelos de domínio do provedor de identidade (Zitadel) vistos pelo Observer."""

from dataclasses import dataclass


class ProviderError(Exception):
    """Qualquer falha ao consultar o Zitadel (rede, timeout, 4xx/5xx, JSON inválido).

    Para o Observer, toda falha de leitura é inconclusiva (`presence = unknown`), nunca `absent`
    (`docs/RESOURCE-CONTROL-SECURITY.md` §8).
    """


@dataclass(frozen=True, slots=True)
class IdentityProjectRole:
    """Role de projeto lida de `roles-<módulo>` no Zitadel (API v2)."""

    key: str
    display_name: str
    group: str
