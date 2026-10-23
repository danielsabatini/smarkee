"""Mapeamento das linhas do SSOT para os contratos de resposta do Receiver.

Nunca expõe campos internos (`failure_count`, `requested_by`) nem o dono da Billing Account
(`ownerAccountId`, `x-resourceView: omitted`).
"""

from typing import Any

from bsm_account.common.contracts import generated
from bsm_account.common.resource import MODULE, RESOURCE_TYPE
from bsm_account.receiver.domain.records import OperationRecord, ResourceRecord


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
    "displayName",
    "billingCurrency",
    "billingContacts",
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


def account_view(record: ResourceRecord) -> generated.BillingAccount:
    payload = _common(record)
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "displayName": record.desired["displayName"],
        "billingCurrency": record.desired["billingCurrency"],
        "billingContacts": record.desired["billingContacts"],
        "deletionProtection": record.desired.get("deletionProtection", True),
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.BillingAccount.model_validate(payload)


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
