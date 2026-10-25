"""Registros lidos do SSOT pelas views versionadas (decisão 0004)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    """Linha da view `role_v1`."""

    resource_id: str
    resource_version: int
    desired_generation: int
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


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """Linha da view `role_operation_v1`.

    `requested_by` serve só para autorizar a leitura.
    """

    operation_id: str
    resource_id: str
    operation_type: str
    desired_generation: int | None
    request_digest: str
    operation_status: str
    operation_status_reason: str | None
    requested_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
