"""Catálogos em memória de permissões delegáveis (`ipm.permission`) e roles (`ipm.role`, 0083).

Puro: sem I/O. Nasce com a semente estática do contrato (`GrantablePermission` e as Roles
predefinidas da decisão 0083) para que o Receiver e o Manager operem imediatamente na partida, e é
atualizado em tempo real pelos consumers de estado (`manager.desired.ipm.permission.>` e
`manager.desired.ipm.role.>`) sem exigir redeploy.
"""

import contextlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from ipm_user.common.contracts import generated

MODULE_PREFIX = "ipm."

PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles predefinidas; valem em qualquer Organization (0092)."""


def _load_access_definitions() -> tuple[set[str], dict[str, list[str]]]:
    """Carrega o catálogo declarativo a partir de access.v1.json (Ajuste 2 / S0)."""
    candidates = (
        Path(__file__).resolve().parent / "access.v1.json",
        Path(__file__).resolve().parents[4] / "schemas" / "ipm" / "access.v1.json",
        Path("/app/schemas/ipm/access.v1.json"),
    )
    for path in candidates:
        if path.is_file():
            with contextlib.suppress(Exception):
                data = json.loads(path.read_text(encoding="utf-8"))
                perms = set(data.get("grantablePermissions", []))
                roles = {str(k): list(v) for k, v in data.get("predefinedRoles", {}).items()}
                if perms and roles:
                    return perms, roles
    perms = {permission.value for permission in generated.GrantablePermission}
    return perms, {}


_GRANTABLE_PERMISSIONS, _PREDEFINED_ROLES = _load_access_definitions()


def default_grantable_permissions() -> set[str]:
    """Conjunto inicial de permissões delegáveis à Organization (`GrantablePermission`)."""
    return set(_GRANTABLE_PERMISSIONS)


def default_roles_catalog() -> dict[str, list[str]]:
    """Mapa inicial `roleName -> permissions` das Roles predefinidas (decisão 0083)."""
    return {name: list(perms) for name, perms in _PREDEFINED_ROLES.items()}


class AccessCatalog:
    """Catálogo de permissões `grantable`, Roles compostas e Grupos (0083, 0088)."""

    def __init__(
        self,
        *,
        grantable_permissions: Iterable[str] | None = None,
        roles: Mapping[str, Iterable[str]] | None = None,
        groups: Mapping[tuple[str, str], Iterable[str]] | None = None,
    ) -> None:
        self._grantable: set[str] = (
            set(grantable_permissions)
            if grantable_permissions is not None
            else default_grantable_permissions()
        )
        # Chave `(organização, nome)`: as predefinidas ficam em `core` e valem para todas; as
        # `custom` só valem na Organization dona (decisão 0092).
        initial = roles if roles is not None else default_roles_catalog()
        self._roles: dict[tuple[str, str], list[str]] = {
            (PLATFORM_ORGANIZATION_ID, name): sorted(set(perms)) for name, perms in initial.items()
        }
        self._groups: dict[tuple[str, str], list[str]] = (
            {(org, name): sorted(set(r)) for (org, name), r in groups.items()}
            if groups is not None
            else {}
        )
        self._permission_names_by_id: dict[str, str] = {}
        self._role_keys_by_id: dict[str, tuple[str, str]] = {}
        self._group_keys_by_id: dict[str, tuple[str, str]] = {}

    @property
    def grantable_permissions(self) -> set[str]:
        return set(self._grantable)

    @property
    def roles(self) -> dict[str, list[str]]:
        """Roles predefinidas da plataforma (`core`), por nome."""
        return {
            name: list(perms)
            for (organization_id, name), perms in self._roles.items()
            if organization_id == PLATFORM_ORGANIZATION_ID
        }

    def _role_permissions(self, role_name: str, organization_id: str) -> list[str]:
        """Permissões da Role visível à Organization: a própria `custom` ou a predefinida."""
        found = self._roles.get((organization_id, role_name))
        if found is None:
            found = self._roles.get((PLATFORM_ORGANIZATION_ID, role_name))
        return found or []

    def is_role_grantable(
        self, role_name: str, organization_id: str = PLATFORM_ORGANIZATION_ID
    ) -> bool:
        """Uma Role é atribuível a um usuário de Organization se concede permissões dela."""
        perms = self._role_permissions(role_name, organization_id)
        if not perms:
            return False
        if set(perms) <= self._grantable:
            return True
        # `ipm.organizationAdmin` inclui `create`/`delete` (escopo de conta), mas na Organization
        # concede as permissões delegáveis de `ipm.organization.*` (`get`, `list`, `update`).
        return role_name == "ipm.organizationAdmin" and bool(set(perms) & self._grantable)

    def expand_roles(
        self, role_names: Iterable[str], organization_id: str = PLATFORM_ORGANIZATION_ID
    ) -> list[str]:
        """Expande Roles em permissões atômicas delegáveis à Organization, sem repetição."""
        expanded: set[str] = set()
        for role_name in role_names:
            for perm in self._role_permissions(role_name, organization_id):
                if perm in self._grantable:
                    expanded.add(perm)
        return sorted(expanded)

    def group_roles(self, organization_id: str, group_name: str) -> list[str]:
        """Roles atribuídas ao grupo na Organization."""
        return list(self._groups.get((organization_id, group_name), []))

    def expand_groups(self, organization_id: str, group_names: Iterable[str]) -> list[str]:
        """Expande grupos nas suas roles compostas na Organization."""
        roles: set[str] = set()
        for g_name in group_names:
            roles.update(self._groups.get((organization_id, g_name), ()))
        return sorted(roles)

    def is_group_known(self, organization_id: str, group_name: str) -> bool:
        """Informa se o grupo está registrado na Organization."""
        return (organization_id, group_name) in self._groups

    def effective_permissions(
        self,
        direct_permissions: Iterable[str],
        role_names: Iterable[str],
        organization_id: str = PLATFORM_ORGANIZATION_ID,
    ) -> list[str]:
        """União ordenada entre as permissões atômicas diretas e as expandidas das Roles."""
        return sorted(set(direct_permissions) | set(self.expand_roles(role_names, organization_id)))

    def apply_permission_desired(self, resource_id: str, payload: Mapping[str, Any]) -> bool:
        """Aplica um evento `desired` de `ipm.permission`; devolve `True` se o catálogo mudou."""
        name = payload.get("name")
        if isinstance(name, str) and name:
            previous = self._permission_names_by_id.get(resource_id)
            if previous and previous != name:
                self._grantable.discard(previous)
            self._permission_names_by_id[resource_id] = name
        else:
            name = self._permission_names_by_id.get(resource_id)
        if not isinstance(name, str) or not name.startswith(MODULE_PREFIX):
            return False
        before = set(self._grantable)
        if payload.get("lifecycle") == "present" and payload.get("grantable") is True:
            self._grantable.add(name)
        else:
            self._grantable.discard(name)
        return self._grantable != before

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
            previous = self._role_keys_by_id.get(resource_id)
            if previous and previous != key:
                self._roles.pop(previous, None)
            self._role_keys_by_id[resource_id] = key
        else:
            key = self._role_keys_by_id.get(resource_id)
        if key is None:
            return False
        before = dict(self._roles)
        if payload.get("lifecycle") == "present":
            raw_perms = payload.get("permissions")
            perms = (
                sorted({p for p in cast(list[Any], raw_perms) if isinstance(p, str)})
                if isinstance(raw_perms, list)
                else []
            )
            self._roles[key] = perms
        else:
            self._roles.pop(key, None)
        return self._roles != before

    def apply_group_desired(self, resource_id: str, payload: Mapping[str, Any]) -> bool:
        """Aplica um evento `desired` de `ipm.group`; devolve `True` se o catálogo mudou."""
        org_id = payload.get("organizationId")
        name = payload.get("name")
        if isinstance(org_id, str) and isinstance(name, str) and org_id and name:
            key = (org_id, name)
            previous = self._group_keys_by_id.get(resource_id)
            if previous and previous != key:
                self._groups.pop(previous, None)
            self._group_keys_by_id[resource_id] = key
        else:
            key = self._group_keys_by_id.get(resource_id)
        if key is None:
            return False
        before = dict(self._groups)
        if payload.get("lifecycle") == "present":
            raw_roles = payload.get("roles")
            roles = (
                sorted({r for r in cast(list[Any], raw_roles) if isinstance(r, str)})
                if isinstance(raw_roles, list)
                else []
            )
            self._groups[key] = roles
        else:
            self._groups.pop(key, None)
        return self._groups != before
