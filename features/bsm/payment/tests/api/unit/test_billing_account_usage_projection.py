"""Testes unitários de `BillingAccountUsageProjection` (`bsm.payment`, decisão 0100)."""

import json
from datetime import UTC, datetime

from bsm_payment.api.transport.billing_account_usage_projection import (
    BillingAccountUsageProjection,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC).isoformat()


def _message(
    resource_id: str,
    *,
    lifecycle: str = "present",
    payment_id: str | None = "pm-01",
    message_type: str = "desired",
    module: str = "bsm",
    resource_type: str = "account",
) -> bytes:
    data: dict[str, object] = {
        "lifecycle": lifecycle,
        "reconciliation": "active",
        "type": "paid" if payment_id else "free",
        "customerAccountId": "user-1",
        "displayName": "Conta",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.example"],
        "ownerAccountId": "user-1",
    }
    if payment_id is not None:
        data["paymentId"] = payment_id
    return json.dumps(
        {
            "messageId": f"msg-{resource_id}",
            "schemaVersion": "1.0",
            "messageType": message_type,
            "emitter": "api",
            "module": module,
            "resourceType": resource_type,
            "resourceId": resource_id,
            "operation": "changed",
            "desiredGeneration": 1,
            "requestedBy": "user-1",
            "correlationId": "corr-1",
            "occurredAt": NOW,
            "publishedAt": NOW,
            "data": data,
        }
    ).encode("utf-8")


async def test_tracks_active_billing_accounts_and_releases_when_absent_or_switched() -> None:
    projection = BillingAccountUsageProjection()
    assert not projection.has_attached_billing_accounts("pm-01")

    await projection.on_message(_message("ba-1", payment_id="pm-01"))
    assert projection.has_attached_billing_accounts("pm-01")

    # Troca para outro método de pagamento libera o anterior
    await projection.on_message(_message("ba-1", payment_id="pm-02"))
    assert not projection.has_attached_billing_accounts("pm-01")
    assert projection.has_attached_billing_accounts("pm-02")

    # Remoção libera o método atual
    await projection.on_message(_message("ba-1", lifecycle="absent", payment_id="pm-02"))
    assert not projection.has_attached_billing_accounts("pm-02")


async def test_ignores_invalid_or_unrelated_messages() -> None:
    projection = BillingAccountUsageProjection()
    assert await projection.on_message(b"not-json") is True
    assert await projection.on_message(_message("ba-1", module="ipm")) is True
    assert not projection.has_attached_billing_accounts("pm-01")
