"""Mapeamento das linhas do SSOT para os contratos de resposta da API.

Nunca expõe campos internos (`failure_count`, `requested_by`) nem o dono da Organization.
"""

from typing import Any

from core.api.repository import OperationRecord, ResourceRecord
from core.contracts import generated

MODULE = "core"
USER_DESIRED_FIELDS = ("givenName", "familyName", "email")


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


def _observed(record: ResourceRecord) -> dict[str, Any] | None:
    if record.presence is None or record.observed_at is None:
        return None
    return {
        "presence": record.presence,
        "observedAt": record.observed_at.isoformat(),
        **(record.observed or {}),
    }


def organization_view(record: ResourceRecord) -> generated.Organization:
    payload = _common(record)
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "name": record.desired["name"],
        "platformAccess": record.desired["platformAccess"],
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.Organization.model_validate(payload)


def user_view(record: ResourceRecord) -> generated.User:
    payload = _common(record)
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "platformAccess": record.desired["platformAccess"],
        **{
            field: record.desired[field] for field in USER_DESIRED_FIELDS if field in record.desired
        },
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.User.model_validate(payload)


def operation_view(record: OperationRecord) -> generated.Operation:
    payload: dict[str, Any] = {
        "operationId": record.operation_id,
        "operationType": record.operation_type,
        "module": MODULE,
        "resourceType": record.resource_type,
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
