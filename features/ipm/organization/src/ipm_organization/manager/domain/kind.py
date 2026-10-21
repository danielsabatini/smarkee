"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_organization.manager.domain.organization import OrganizationPolicy
from ipm_organization.manager.domain.policy import ResourcePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


def organization_kind(user_access: Mapping[str, Any] | None) -> ResourceKind:
    """A Organization, com o `userAccess` que o Manager grava no `desired` (decisão 0081)."""
    return ResourceKind(resource_type="organization", policy=OrganizationPolicy(user_access))


ORGANIZATION = organization_kind(None)
"""Sem `userAccess`: o tipo como era antes da decisão 0081 (testes e leitura)."""
