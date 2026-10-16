"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from ipm_organization_manager.domain.organization import OrganizationPolicy
from ipm_organization_manager.domain.policy import ResourcePolicy

MODULE = "ipm"


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy

    @property
    def requested_filter_subject(self) -> str:
        """Filtro do consumer de `requested` do tipo (`docs/NATS.md` §7)."""
        return f"receiver.requested.{MODULE}.{self.resource_type}.>"


ORGANIZATION = ResourceKind(resource_type="organization", policy=OrganizationPolicy())
