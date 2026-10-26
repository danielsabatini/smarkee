"""Catálogo em memória de Roles compostas delegáveis (`ipm.role`, decisões 0083 e 0088).

Puro: sem I/O. Nasce com a semente estática das Roles predefinidas da plataforma e é atualizado
em tempo real pelos consumers de estado (`manager.desired.ipm.role.>`) sem exigir redeploy.
"""

from collections.abc import Iterable, Mapping
from typing import Any, cast

PREDEFINED_ROLES: dict[str, list[str]] = {
    "bsm.accountViewer": ["bsm.account.get", "bsm.account.list"],
    "bsm.accountAdmin": [
        "bsm.account.create",
        "bsm.account.delete",
        "bsm.account.get",
        "bsm.account.list",
        "bsm.account.update",
    ],
    "core.accountViewer": ["core.account.get"],
    "core.accountAdmin": ["core.account.delete", "core.account.get"],
    "sum.serviceViewer": ["sum.ipm.get"],
    "sum.serviceAdmin": ["sum.ipm.disable", "sum.ipm.enable", "sum.ipm.get"],
    "ipm.organizationViewer": ["ipm.organization.get", "ipm.organization.list"],
    "ipm.organizationAdmin": [
        "ipm.organization.create",
        "ipm.organization.delete",
        "ipm.organization.get",
        "ipm.organization.list",
        "ipm.organization.update",
    ],
    "ipm.userViewer": ["ipm.user.get", "ipm.user.list"],
    "ipm.userAdmin": [
        "ipm.user.bind",
        "ipm.user.create",
        "ipm.user.delete",
        "ipm.user.get",
        "ipm.user.list",
        "ipm.user.update",
    ],
    "ipm.groupViewer": ["ipm.group.get", "ipm.group.list"],
    "ipm.groupAdmin": [
        "ipm.group.bind",
        "ipm.group.create",
        "ipm.group.delete",
        "ipm.group.get",
        "ipm.group.list",
        "ipm.group.update",
    ],
    "ipm.permissionViewer": ["ipm.permission.get", "ipm.permission.list"],
    "ipm.permissionAdmin": [
        "ipm.permission.admin",
        "ipm.permission.get",
        "ipm.permission.list",
    ],
    "ipm.roleViewer": ["ipm.role.get", "ipm.role.list"],
    "ipm.roleAdmin": ["ipm.role.admin", "ipm.role.get", "ipm.role.list"],
}


def default_roles_catalog() -> dict[str, list[str]]:
    """Mapa inicial `roleName -> permissions` das Roles predefinidas."""
    return {name: list(perms) for name, perms in PREDEFINED_ROLES.items()}


class RolesCatalog:
    """Catálogo dinâmico de Roles compostas."""

    def __init__(self, roles: Mapping[str, Iterable[str]] | None = None) -> None:
        initial = roles if roles is not None else default_roles_catalog()
        self._roles: dict[str, list[str]] = {
            name: sorted(set(perms)) for name, perms in initial.items()
        }

    def is_known_role(self, role_name: str) -> bool:
        return role_name in self._roles

    def outside_catalog(self, roles: Iterable[str]) -> list[str]:
        return sorted([r for r in set(roles) if r not in self._roles])

    def update_role(self, role_name: str, permissions: Iterable[str]) -> None:
        self._roles[role_name] = sorted(set(permissions))

    def remove_role(self, role_name: str) -> None:
        self._roles.pop(role_name, None)

    def on_role_desired(self, data: Mapping[str, Any]) -> None:
        name = str(data.get("name", ""))
        if not name:
            return
        if data.get("lifecycle") == "absent":
            self.remove_role(name)
            return
        perms = cast(list[Any], data.get("permissions") or [])
        self.update_role(name, [str(p) for p in perms])
