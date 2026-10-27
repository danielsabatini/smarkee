"""Catálogo em memória de Roles compostas delegáveis (`ipm.role`, decisões 0083 e 0088).

Puro: sem I/O. Nasce com a semente estática das Roles predefinidas da plataforma e é atualizado
em tempo real pelos consumers de estado (`manager.desired.ipm.role.>`) sem exigir redeploy.
"""

import contextlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles predefinidas; valem em qualquer Organization."""


def _load_access_definitions() -> dict[str, list[str]]:
    """Carrega o catálogo de roles predefinidas a partir de access.v1.json (Ajuste 2 / S0)."""
    candidates = (
        Path(__file__).resolve().parent / "access.v1.json",
        Path(__file__).resolve().parents[4] / "schemas" / "ipm" / "access.v1.json",
        Path("/app/schemas/ipm/access.v1.json"),
    )
    for path in candidates:
        if path.is_file():
            with contextlib.suppress(Exception):
                data = json.loads(path.read_text(encoding="utf-8"))
                roles = {str(k): list(v) for k, v in data.get("predefinedRoles", {}).items()}
                if roles:
                    return roles
    return {}


_PREDEFINED_ROLES = _load_access_definitions()


def default_roles_catalog() -> dict[str, list[str]]:
    """Mapa inicial `roleName -> permissions` das Roles predefinidas."""
    return {name: list(perms) for name, perms in _PREDEFINED_ROLES.items()}


class RolesCatalog:
    """Catálogo dinâmico de Roles compostas, por `(organização, nome)` (decisão 0092).

    As predefinidas (`core`) valem em qualquer Organization; as `custom` só na própria.
    """

    def __init__(self, roles: Mapping[str, Iterable[str]] | None = None) -> None:
        initial = roles if roles is not None else default_roles_catalog()
        self._roles: dict[tuple[str, str], list[str]] = {
            (PLATFORM_ORGANIZATION_ID, name): sorted(set(perms)) for name, perms in initial.items()
        }
        self._keys_by_id: dict[str, tuple[str, str]] = {}

    def is_known_role(
        self, role_name: str, organization_id: str = PLATFORM_ORGANIZATION_ID
    ) -> bool:
        return (organization_id, role_name) in self._roles or (
            PLATFORM_ORGANIZATION_ID,
            role_name,
        ) in self._roles

    def outside_catalog(
        self, roles: Iterable[str], organization_id: str = PLATFORM_ORGANIZATION_ID
    ) -> list[str]:
        """Roles que não existem para a Organization (nem predefinidas, nem `custom` dela)."""
        return sorted(r for r in set(roles) if not self.is_known_role(r, organization_id))

    def apply_role_desired(self, resource_id: str, payload: Mapping[str, Any]) -> bool:
        """Aplica um evento `desired` de `ipm.role`; devolve `True` se o catálogo mudou."""
        name = payload.get("name")
        if isinstance(name, str) and name:
            organization_id = payload.get("organizationId")
            key = (
                organization_id
                if isinstance(organization_id, str) and organization_id
                else PLATFORM_ORGANIZATION_ID,
                name,
            )
            previous = self._keys_by_id.get(resource_id)
            if previous and previous != key:
                self._roles.pop(previous, None)
            self._keys_by_id[resource_id] = key
        else:
            key = self._keys_by_id.get(resource_id)
        if key is None:
            return False
        before = dict(self._roles)
        if payload.get("lifecycle") == "present":
            raw = payload.get("permissions")
            self._roles[key] = (
                sorted({str(p) for p in cast(list[Any], raw)}) if isinstance(raw, list) else []
            )
        else:
            self._roles.pop(key, None)
        return self._roles != before
