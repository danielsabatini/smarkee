"""Catálogo em memória das permissões delegáveis à Organization (`ipm.permission`, decisão 0092).

Puro: sem I/O. Nasce com a semente do contrato (`GrantablePermission`) para que o Receiver opere
na partida e é atualizado em tempo real pelos `desired` de `ipm.permission`, sem redeploy. É o teto
de permissões de uma Role `custom`: ela só pode conter permissões que a Organization pode delegar.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from ipm_role.common.contracts import generated

MODULE_PREFIX = "ipm."


def default_grantable_permissions() -> set[str]:
    """Conjunto inicial de permissões delegáveis à Organization (`GrantablePermission`)."""
    return {permission.value for permission in generated.GrantablePermission}


class GrantableCatalog:
    """Permissões `grantable`, mantidas a partir dos eventos `desired` de `ipm.permission`."""

    def __init__(self, grantable_permissions: Iterable[str] | None = None) -> None:
        self._grantable: set[str] = (
            set(grantable_permissions)
            if grantable_permissions is not None
            else default_grantable_permissions()
        )
        self._names_by_id: dict[str, str] = {}

    @property
    def grantable_permissions(self) -> set[str]:
        return set(self._grantable)

    def outside(self, permissions: Iterable[str]) -> list[str]:
        """Permissões pedidas que a Organization não pode delegar, em ordem alfabética."""
        return sorted(item for item in set(permissions) if item not in self._grantable)

    def apply_permission_desired(self, resource_id: str, payload: Mapping[str, Any]) -> bool:
        """Aplica um evento `desired` de `ipm.permission`; devolve `True` se o catálogo mudou."""
        name = payload.get("name")
        if isinstance(name, str) and name:
            previous = self._names_by_id.get(resource_id)
            if previous and previous != name:
                self._grantable.discard(previous)
            self._names_by_id[resource_id] = name
        else:
            name = self._names_by_id.get(resource_id)
        if not isinstance(name, str) or not name.startswith(MODULE_PREFIX):
            return False
        before = set(self._grantable)
        if payload.get("lifecycle") == "present" and payload.get("grantable") is True:
            self._grantable.add(name)
        else:
            self._grantable.discard(name)
        return self._grantable != before
