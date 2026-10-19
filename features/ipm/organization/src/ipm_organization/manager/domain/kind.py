"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from ipm_organization.manager.domain.organization import OrganizationPolicy
from ipm_organization.manager.domain.policy import ResourcePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy


ORGANIZATION = ResourceKind(resource_type="organization", policy=OrganizationPolicy())
