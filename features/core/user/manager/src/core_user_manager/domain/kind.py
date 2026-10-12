"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from core_user_manager.domain.policy import ResourcePolicy
from core_user_manager.domain.user import UserPolicy

MODULE = "core"


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy

    @property
    def requested_filter_subject(self) -> str:
        """Filtro do consumer de `requested` do tipo (`docs/NATS.md` §7)."""
        return f"receiver.requested.{MODULE}.{self.resource_type}.>"


USER = ResourceKind(resource_type="user", policy=UserPolicy())
