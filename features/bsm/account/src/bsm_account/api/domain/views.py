"""Mapeamento das linhas do SSOT para os contratos de resposta da API (decisões 0004 e 0098).

Nunca expõe campos internos (`failure_count`, `requested_by`) nem o dono da Billing Account
(`ownerAccountId`, `x-resourceView: omitted`).
"""

from typing import Any

from bsm_account.api.domain.records import ResourceRecord
from bsm_account.common.contracts import generated


def account_view(record: ResourceRecord) -> generated.BillingAccount:
    payload: dict[str, Any] = {
        "resourceId": record.resource_id,
        "resourceVersion": str(record.resource_version),
        "desiredGeneration": record.desired_generation,
        "phase": record.phase,
        "conditions": record.conditions,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "desired": {
            "lifecycle": record.lifecycle,
            "reconciliation": record.reconciliation,
            "displayName": record.desired["displayName"],
            "billingCurrency": record.desired["billingCurrency"],
            "billingContacts": record.desired["billingContacts"],
            "deletionProtection": record.desired.get("deletionProtection", True),
        },
    }
    observed = record.observed
    if observed is not None and record.presence is not None and record.observed_at is not None:
        payload["observed"] = {
            "presence": record.presence,
            "observedAt": record.observed_at.isoformat(),
            "displayName": observed.get("displayName", record.desired["displayName"]),
            "billingCurrency": observed.get("billingCurrency", record.desired["billingCurrency"]),
            "billingContacts": observed.get("billingContacts", record.desired["billingContacts"]),
            "deletionProtection": observed.get(
                "deletionProtection", record.desired.get("deletionProtection", True)
            ),
        }
    return generated.BillingAccount.model_validate(payload)
