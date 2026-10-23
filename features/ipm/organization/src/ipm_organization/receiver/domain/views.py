"""Mapeamento das linhas do SSOT para os contratos de resposta do Receiver.

Nunca expõe campos internos (`failure_count`, `requested_by`), o dono da Organization nem o
preparo para os usuários (`userAccess`).
"""

from typing import Any

from ipm_organization.common.contracts import generated
from ipm_organization.common.resource import MODULE, RESOURCE_TYPE
from ipm_organization.receiver.domain.records import OperationRecord, ResourceRecord


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


OBSERVED_VIEW_FIELDS = ("name", "platformAccess", "organizationState", "deletionProtection")
"""Campos do `observed` que a visão mostra, um a um: o `userAccess` (IDs de contas de serviço da
plataforma) fica de fora (`x-resourceView: omitted`, decisão 0081)."""


def _observed(record: ResourceRecord) -> dict[str, Any] | None:
    if record.presence is None or record.observed_at is None:
        return None
    observed = record.observed or {}
    return {
        "presence": record.presence,
        "observedAt": record.observed_at.isoformat(),
        **{field: observed[field] for field in OBSERVED_VIEW_FIELDS if field in observed},
    }


def organization_view(record: ResourceRecord) -> generated.Organization:
    payload = _common(record)
    desired: dict[str, Any] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "name": record.desired["name"],
        "platformAccess": record.desired["platformAccess"],
        # Registro sem o campo (anterior à proteção) conta como protegido.
        "deletionProtection": record.desired.get("deletionProtection", True),
    }
    if "billingAccountId" in record.desired:
        desired["billingAccountId"] = record.desired["billingAccountId"]
    payload["desired"] = desired
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.Organization.model_validate(payload)


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
