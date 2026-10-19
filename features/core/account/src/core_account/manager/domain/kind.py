"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from core_account.manager.domain.account import AccountPolicy
from core_account.manager.domain.policy import ResourcePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy


def account_kind(platform_roles: tuple[str, ...]) -> ResourceKind:
    """Account com o conjunto de roles informado (configuração do Manager)."""
    return ResourceKind(resource_type="account", policy=AccountPolicy(platform_roles))
