"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from ipm_user.manager.domain.policy import ResourcePolicy
from ipm_user.manager.domain.user import UserPolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


def user_kind() -> ResourceKind:
    return ResourceKind(resource_type="user", policy=UserPolicy())


USER = user_kind()
