"""Mapeamento das linhas do SSOT para os contratos de resposta da API (decisões 0004 e 0098).

Nunca expõe campos internos (`failure_count`, `requested_by`), o dono (`ownerAccountId`)
nem o token de uso único/referência (`providerToken`).
"""

from typing import Any

from bsm_payment.api.domain.records import ResourceRecord
from bsm_payment.common.contracts import generated


def payment_view(record: ResourceRecord) -> generated.Payment:
    customer_account_id = str(
        record.desired.get("customerAccountId") or record.desired["ownerAccountId"]
    )
    payload: dict[str, Any] = {
        "resourceId": record.resource_id,
        "resourceVersion": str(record.resource_version),
        "desiredGeneration": record.desired_generation,
        **(
            {"observedGeneration": record.observed_generation}
            if record.observed_generation is not None
            else {}
        ),
        "phase": record.phase,
        "conditions": record.conditions,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "desired": {
            "lifecycle": record.lifecycle,
            "reconciliation": record.reconciliation,
            "customerAccountId": customer_account_id,
            "displayName": record.desired["displayName"],
            "provider": record.desired["provider"],
            "methodType": record.desired["methodType"],
            "deletionProtection": record.desired.get("deletionProtection", True),
        },
    }
    observed = record.observed
    if observed is not None and record.presence is not None and record.observed_at is not None:
        observed_payload: dict[str, Any] = {
            "presence": record.presence,
            "observedAt": record.observed_at.isoformat(),
        }
        for key in (
            "customerAccountId",
            "displayName",
            "provider",
            "methodType",
            "status",
            "providerCustomerId",
            "providerPaymentMethodId",
            "brand",
            "lastFourDigits",
            "expirationMonth",
            "expirationYear",
            "deletionProtection",
        ):
            if key in observed and observed[key] is not None:
                observed_payload[key] = observed[key]
        payload["observed"] = observed_payload
    return generated.Payment.model_validate(payload)
