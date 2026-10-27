"""Registros lidos do SSOT pelas views versionadas (decisão 0004)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    """Linha do recurso, lida da view `permission_v1` (ou da tabela, na admissão)."""

    resource_id: str
    resource_version: int
    desired_generation: int
    observed_generation: int | None
    lifecycle: str
    reconciliation: str
    phase: str
    conditions: list[dict[str, Any]]
    desired: dict[str, Any]
    presence: str | None
    observed: dict[str, Any] | None
    observed_at: datetime | None
    created_at: datetime
    updated_at: datetime
