"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from ipm_permission.manager.domain.permission import PermissionPolicy
from ipm_permission.manager.domain.policy import ResourcePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


PERMISSION = ResourceKind(resource_type="permission", policy=PermissionPolicy())
