"""Tipo de recurso tratado pelos handlers do template: identificação e política (decisão 0080)."""

from dataclasses import dataclass

from sum_service.manager.domain.policy import ResourcePolicy
from sum_service.manager.domain.service import ServicePolicy


@dataclass(frozen=True, slots=True)
class ResourceKind:
    resource_type: str
    policy: ResourcePolicy
    removes_absent: bool = True
    """A remoção convergida apaga o registro do SSOT (o padrão do loop)."""


SERVICE = ResourceKind(resource_type="service", policy=ServicePolicy(), removes_absent=False)
"""A ligação desfeita continua existindo (decisão 0033): o registro não é apagado."""
