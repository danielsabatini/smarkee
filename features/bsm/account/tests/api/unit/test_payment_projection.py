"""Testes unitários de `PaymentProjection` (`bsm.account`, decisão 0100)."""

import json
from datetime import UTC, datetime

from bsm_account.api.transport.payment_projection import PaymentProjection

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC).isoformat()


def _message(
    resource_id: str,
    *,
    lifecycle: str = "present",
    reconciliation: str = "active",
    customer_account_id: str = "user-1",
    message_type: str = "desired",
    module: str = "bsm",
    resource_type: str = "payment",
) -> bytes:
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
            "requestedBy": customer_account_id,
            "correlationId": "corr-1",
            "occurredAt": NOW,
            "publishedAt": NOW,
            "data": {
                "lifecycle": lifecycle,
                "reconciliation": reconciliation,
                "customerAccountId": customer_account_id,
                "displayName": "Visa Final 4242",
                "provider": "mercadopago",
                "methodType": "credit_card",
                "providerToken": "tok_test_apro_4242",
                "ownerAccountId": customer_account_id,
            },
        }
    ).encode("utf-8")


async def test_tracks_active_payments_per_customer_and_evicts_suspended_or_absent() -> None:
    projection = PaymentProjection()
    assert not projection.is_active_payment("pm-1", "user-1")

    await projection.on_message(_message("pm-1", customer_account_id="user-1"))
    assert projection.is_active_payment("pm-1", "user-1")
    assert not projection.is_active_payment("pm-1", "user-2")

    # Suspenso pelo controller após falhas não é considerado ativo
    await projection.on_message(
        _message("pm-1", customer_account_id="user-1", reconciliation="suspended")
    )
    assert not projection.is_active_payment("pm-1", "user-1")

    # Reativado
    await projection.on_message(_message("pm-1", customer_account_id="user-1"))
    assert projection.is_active_payment("pm-1", "user-1")

    # Removido
    await projection.on_message(_message("pm-1", lifecycle="absent"))
    assert not projection.is_active_payment("pm-1", "user-1")


async def test_ignores_invalid_or_unrelated_messages() -> None:
    projection = PaymentProjection()
    assert await projection.on_message(b"not-json") is True
    assert await projection.on_message(_message("pm-1", module="ipm")) is True
    assert not projection.is_active_payment("pm-1", "user-1")
