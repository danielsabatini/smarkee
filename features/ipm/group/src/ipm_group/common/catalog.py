"""Catálogo em memória de Roles compostas delegáveis (`ipm.role`, decisões 0083 e 0088).

Puro: sem I/O. Nasce com a semente estática das Roles predefinidas da plataforma e é atualizado
em tempo real pelos consumers de estado (`manager.desired.ipm.role.>`) sem exigir redeploy.
"""

from collections.abc import Iterable, Mapping
from typing import Any, cast

PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles predefinidas; valem em qualquer Organization."""

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
    "ipm.serviceaccountViewer": ["ipm.serviceaccount.get", "ipm.serviceaccount.list"],
    "ipm.serviceaccountAdmin": [
        "ipm.serviceaccount.bind",
        "ipm.serviceaccount.create",
        "ipm.serviceaccount.delete",
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
        "ipm.serviceaccount.update",
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
