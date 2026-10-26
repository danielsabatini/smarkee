"""Contrato da política do tipo que os handlers do template usam (perfil `manager-handlers`).

Puro, sem I/O. Os pedidos (`requested`) do SUM seguem as regras próprias de `domain/decision.py`;
esta política só responde à convergência e ao formato do `desired` publicado (decisão 0080).
"""

from collections.abc import Mapping
from typing import Any, Protocol


class ResourcePolicy(Protocol):
    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]: ...

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        """Compara `desired` e `observed` pelos campos gerenciados (`docs/data/SCHEMA.md` §9.1)."""
        ...
