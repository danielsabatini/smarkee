"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from core_account.manager.domain.account import AccountPolicy
from core_account.manager.domain.policy import ResourcePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


def account_kind(platform_permissions: tuple[str, ...]) -> ResourceKind:
    """Account com o conjunto de permissões informado (configuração do Manager)."""
    return ResourceKind(resource_type="account", policy=AccountPolicy(platform_permissions))
