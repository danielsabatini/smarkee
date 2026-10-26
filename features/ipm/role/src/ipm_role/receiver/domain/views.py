"""Mapeamento das linhas do SSOT para os contratos de resposta do Receiver.

Nunca expõe campos internos (`failure_count`, `requested_by`).
"""

from typing import Any

from ipm_role.common.contracts import generated
from ipm_role.common.resource import MODULE, RESOURCE_TYPE
from ipm_role.receiver.domain.records import OperationRecord, ResourceRecord

PLATFORM_ORGANIZATION_ID = "core"
"""Dado anterior à decisão 0092 não tem `organizationId`: vale `core`."""


def _common(record: ResourceRecord) -> dict[str, Any]:
    return {
        "resourceId": record.resource_id,
        "resourceVersion": str(record.resource_version),
        "desiredGeneration": record.desired_generation,
        "phase": record.phase,
        "conditions": record.conditions,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


OBSERVED_VIEW_FIELDS = (
    "name",
    "description",
    "permissions",
    "deletionProtection",
)
"""Campos do `observed` que a visão mostra."""


def _observed(record: ResourceRecord) -> dict[str, Any] | None:
    if record.presence is None or record.observed_at is None:
        return None
    observed = record.observed or {}
    return {
        "presence": record.presence,
        "observedAt": record.observed_at.isoformat(),
        **{field: observed[field] for field in OBSERVED_VIEW_FIELDS if field in observed},
    }


def role_view(record: ResourceRecord) -> generated.Role:
    payload = _common(record)
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "organizationId": record.desired.get("organizationId", PLATFORM_ORGANIZATION_ID),
        "name": record.desired["name"],
        "roleType": record.desired.get("roleType", "custom"),
        "description": record.desired["description"],
        "permissions": record.desired["permissions"],
        "deletionProtection": record.desired.get("deletionProtection", True) is not False,
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.Role.model_validate(payload)


def operation_view(record: OperationRecord) -> generated.Operation:
    payload: dict[str, Any] = {
        "operationId": record.operation_id,
        "operationType": record.operation_type,
        "module": MODULE,
        "resourceType": RESOURCE_TYPE,
        "resourceId": record.resource_id,
        "operationStatus": record.operation_status,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }
    if record.desired_generation is not None:
        payload["desiredGeneration"] = record.desired_generation
    if record.operation_status_reason is not None:
        payload["operationStatusReason"] = record.operation_status_reason
    if record.completed_at is not None:
        payload["completedAt"] = record.completed_at.isoformat()
    return generated.Operation.model_validate(payload)
