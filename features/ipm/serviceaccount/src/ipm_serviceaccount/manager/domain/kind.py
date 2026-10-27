"""Tipo de recurso tratado pelo Manager: identificação e política de negócio."""

from dataclasses import dataclass

from ipm_serviceaccount.manager.domain.policy import ResourcePolicy
from ipm_serviceaccount.manager.domain.serviceaccount import ServiceAccountPolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


def serviceaccount_kind() -> ResourceKind:
    return ResourceKind(resource_type="serviceaccount", policy=ServiceAccountPolicy())


SERVICEACCOUNT = serviceaccount_kind()
