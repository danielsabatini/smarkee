"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from core_account_manager.domain.account import AccountPolicy
from core_account_manager.domain.policy import ResourcePolicy

MODULE = "core"


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy

    @property
    def requested_filter_subject(self) -> str:
        """Filtro do consumer de `requested` do tipo (`docs/NATS.md` §7)."""
        return f"receiver.requested.{MODULE}.{self.resource_type}.>"


def account_kind(platform_roles: tuple[str, ...]) -> ResourceKind:
    """Account com o conjunto de roles informado (configuração do Manager)."""
    return ResourceKind(resource_type="account", policy=AccountPolicy(platform_roles))


ACCOUNT = ResourceKind(resource_type="account", policy=AccountPolicy())
