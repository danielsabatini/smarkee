"""Permissões efetivas do usuário e índice reverso dos catálogos (decisão 0097).

Puro: sem banco, rede ou relógio. O `desired` do usuário guarda só a intenção (`roles` e
`groups`); as permissões que o provedor deve ter são calculadas aqui a partir do catálogo, e o
índice diz quais usuários reconciliar quando uma Role, um Grupo ou uma permissão delegável muda.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from ipm_user.common.catalog import AccessCatalog


def _names(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item) for item in cast("list[object]", value))


@dataclass(frozen=True, slots=True)
class Membership:
    """O que o `desired` do usuário pede ao catálogo: a Organization, as Roles e os Grupos."""

    organization_id: str
    roles: frozenset[str]
    groups: frozenset[str]

    @classmethod
    def of(cls, desired: Mapping[str, Any]) -> Membership:
        return cls(
            organization_id=str(desired.get("organizationId", "")),
            roles=_names(desired.get("roles")),
            groups=_names(desired.get("groups")),
        )


def effective_permissions(catalog: AccessCatalog, desired: Mapping[str, Any]) -> frozenset[str]:
    """Permissões atômicas delegáveis que o `desired` concede; vazio quando o usuário sai."""
    if desired.get("lifecycle") == "absent":
        return frozenset()
    membership = Membership.of(desired)
    group_roles = catalog.expand_groups(membership.organization_id, membership.groups)
    roles = sorted(membership.roles | set(group_roles))
    return frozenset(catalog.expand_roles(roles, membership.organization_id))


class MembershipIndex:
    """Índice reverso `resourceId -> Membership`, dos usuários da partição.

    Alimentado pelas mensagens `desired` do próprio tipo. Só serve para decidir **quem
    reenfileirar** quando o catálogo muda; o cálculo usa o `desired` lido do SSOT.
    """

    def __init__(self) -> None:
        self._members: dict[str, Membership] = {}

    def __len__(self) -> int:
        return len(self._members)

    def apply(self, resource_id: str, desired: Mapping[str, Any]) -> None:
        if desired.get("lifecycle") == "absent":
            self._members.pop(resource_id, None)
            return
        self._members[resource_id] = Membership.of(desired)

    def with_role(self, role_name: str, catalog: AccessCatalog) -> set[str]:
        """Quem tem a Role direta ou por um Grupo que a atribui."""
        groups = set(catalog.groups_with_role(role_name))
        return {
            resource_id
            for resource_id, member in self._members.items()
            if role_name in member.roles
            or any((member.organization_id, name) in groups for name in member.groups)
        }

    def in_group(self, organization_id: str, group_name: str) -> set[str]:
        return {
            resource_id
            for resource_id, member in self._members.items()
            if member.organization_id == organization_id and group_name in member.groups
        }

    def with_any_access(self) -> set[str]:
        """Quem tem alguma Role ou Grupo: os afetados por uma mudança de permissão delegável."""
        return {
            resource_id
            for resource_id, member in self._members.items()
            if member.roles or member.groups
        }

    def all(self) -> Iterable[str]:
        return tuple(self._members)
