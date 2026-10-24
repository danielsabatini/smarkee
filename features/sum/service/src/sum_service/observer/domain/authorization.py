"""Autorização lida do provedor e o erro de leitura, no vocabulário do domínio.

O adaptador do Zitadel (`provider/`) produz estes tipos; o domínio os consome sem conhecer o
adaptador (decisão 0017). Erro de leitura nunca vira `absent`: o chamador o trata como `unknown`.
"""

from dataclasses import dataclass


class ProviderError(Exception):
    """Leitura do provedor falhou. O chamador trata como observação `unknown`."""


@dataclass(frozen=True, slots=True)
class Authorization:
    project_id: str
    permissions: frozenset[str]
