"""Permissões efetivas da service account e índice reverso do catálogo (decisão 0097).

Puro: sem banco, rede ou relógio. O `desired` da service account guarda só a intenção (`roles`);
as permissões que o provedor deve ter são calculadas aqui a partir do catálogo, e o índice diz
quais service accounts reconciliar quando uma Role ou uma permissão delegável muda.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from ipm_serviceaccount.common.catalog import AccessCatalog


def _names(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item) for item in cast("list[object]", value))


@dataclass(frozen=True, slots=True)
class Membership:
    """O que o `desired` da service account pede ao catálogo: a Organization e as Roles."""

    organization_id: str
    roles: frozenset[str]

    @classmethod
    def of(cls, desired: Mapping[str, Any]) -> Membership:
        return cls(
            organization_id=str(desired.get("organizationId", "")),
            roles=_names(desired.get("roles")),
        )


def effective_permissions(catalog: AccessCatalog, desired: Mapping[str, Any]) -> frozenset[str]:
    """Permissões atômicas delegáveis que o `desired` concede; vazio quando ela sai."""
    if desired.get("lifecycle") == "absent":
        return frozenset()
    membership = Membership.of(desired)
    return frozenset(catalog.expand_roles(sorted(membership.roles), membership.organization_id))


class MembershipIndex:
    """Índice reverso `resourceId -> Membership`, das service accounts da partição.

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

    def with_role(self, role_name: str) -> set[str]:
        """Quem tem a Role."""
        return {rid for rid, member in self._members.items() if role_name in member.roles}

    def with_any_access(self) -> set[str]:
        """Quem tem alguma Role: os afetados por uma mudança de permissão delegável."""
        return {rid for rid, member in self._members.items() if member.roles}
