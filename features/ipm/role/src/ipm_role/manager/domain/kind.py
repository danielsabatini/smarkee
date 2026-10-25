"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from ipm_role.manager.domain.policy import ResourcePolicy
from ipm_role.manager.domain.role import RolePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


ROLE = ResourceKind(resource_type="role", policy=RolePolicy())
