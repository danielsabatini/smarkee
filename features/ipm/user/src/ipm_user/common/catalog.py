"""Catálogos em memória de permissões delegáveis (`ipm.permission`) e roles (`ipm.role`, 0083).

Puro: sem I/O. Nasce com a semente estática do contrato (`GrantablePermission` e as Roles
predefinidas da decisão 0083) para que o Receiver e o Manager operem imediatamente na partida, e é
atualizado em tempo real pelos consumers de estado (`manager.desired.ipm.permission.>` e
`manager.desired.ipm.role.>`) sem exigir redeploy.
"""

from collections.abc import Iterable, Mapping
from typing import Any, cast

from ipm_user.common.contracts import generated

MODULE_PREFIX = "ipm."

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
    "ipm.permissionViewer": ["ipm.permission.get", "ipm.permission.list"],
    "ipm.permissionAdmin": [
        "ipm.permission.admin",
        "ipm.permission.get",
        "ipm.permission.list",
    ],
    "ipm.roleViewer": ["ipm.role.get", "ipm.role.list"],
    "ipm.roleAdmin": ["ipm.role.admin", "ipm.role.get", "ipm.role.list"],
}


def default_grantable_permissions() -> set[str]:
    """Conjunto inicial de permissões delegáveis à Organization (`GrantablePermission`)."""
    return {permission.value for permission in generated.GrantablePermission}


def default_roles_catalog() -> dict[str, list[str]]:
    """Mapa inicial `roleName -> permissions` das Roles predefinidas (decisão 0083)."""
    return {name: list(perms) for name, perms in PREDEFINED_ROLES.items()}


class AccessCatalog:
    """Catálogo dinâmico de permissões `grantable` e de Roles compostas (decisão 0083)."""

    def __init__(
        self,
        *,
        grantable_permissions: Iterable[str] | None = None,
        roles: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self._grantable: set[str] = (
            set(grantable_permissions)
            if grantable_permissions is not None
            else default_grantable_permissions()
        )
        self._roles: dict[str, list[str]] = (
            {name: sorted(set(perms)) for name, perms in roles.items()}
            if roles is not None
            else default_roles_catalog()
        )
        self._permission_names_by_id: dict[str, str] = {}
        self._role_names_by_id: dict[str, str] = {}

    @property
    def grantable_permissions(self) -> set[str]:
        return set(self._grantable)

    @property
    def roles(self) -> dict[str, list[str]]:
        return {name: list(perms) for name, perms in self._roles.items()}

    def is_role_grantable(self, role_name: str) -> bool:
        """Uma Role é atribuível a um usuário de Organization se concede permissões dela."""
        perms = self._roles.get(role_name)
        if not perms:
            return False
        if set(perms) <= self._grantable:
            return True
        # `ipm.organizationAdmin` inclui `create`/`delete` (escopo de conta), mas na Organization
        # concede as permissões delegáveis de `ipm.organization.*` (`get`, `list`, `update`).
        return role_name == "ipm.organizationAdmin" and bool(set(perms) & self._grantable)

    def expand_roles(self, role_names: Iterable[str]) -> list[str]:
        """Expande Roles em permissões atômicas delegáveis à Organization, sem repetição."""
        expanded: set[str] = set()
        for role_name in role_names:
            for perm in self._roles.get(role_name, ()):
                if perm in self._grantable:
                    expanded.add(perm)
        return sorted(expanded)

    def effective_permissions(
        self, direct_permissions: Iterable[str], role_names: Iterable[str]
    ) -> list[str]:
        """União ordenada entre as permissões atômicas diretas e as expandidas das Roles."""
        return sorted(set(direct_permissions) | set(self.expand_roles(role_names)))

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
            previous = self._role_names_by_id.get(resource_id)
            if previous and previous != name:
                self._roles.pop(previous, None)
            self._role_names_by_id[resource_id] = name
        else:
            name = self._role_names_by_id.get(resource_id)
        if not isinstance(name, str) or not name:
            return False
        before = dict(self._roles)
        if payload.get("lifecycle") == "present":
            raw_perms = payload.get("permissions")
            perms = (
                sorted({p for p in cast(list[Any], raw_perms) if isinstance(p, str)})
                if isinstance(raw_perms, list)
                else []
            )
            self._roles[name] = perms
        else:
            self._roles.pop(name, None)
        return self._roles != before
