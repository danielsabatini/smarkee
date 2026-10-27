"""Projeção local de Billing Accounts a partir do stream `DESIRED` (decisão 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_organization.api.transport.billing_account_projection import BillingAccountProjection


def message(resource_id: str, **data: Any) -> bytes:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC).isoformat()
    return json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000001",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "api",
            "module": "bsm",
            "resourceType": "account",
            "resourceId": resource_id,
            "operation": "changed",
            "desiredGeneration": 1,
            "requestedBy": "system",
            "correlationId": "01950000-0000-7000-8000-000000000002",
            "occurredAt": now,
            "publishedAt": now,
            "data": data,
        }
    ).encode()


async def test_a_present_billing_account_belongs_to_its_owner() -> None:
    projection = BillingAccountProjection()
    assert await projection.on_message(
        message("ba-1", lifecycle="present", ownerAccountId="usr-owner")
    )
    assert projection.is_ready_billing_account("ba-1", "usr-owner") is True
    assert projection.is_ready_billing_account("ba-1", "other-user") is False
    assert projection.is_ready_billing_account("unknown", "usr-owner") is False


async def test_a_billing_account_being_removed_is_no_longer_ready() -> None:
    projection = BillingAccountProjection()
    await projection.on_message(message("ba-1", lifecycle="present", ownerAccountId="usr-owner"))
    assert await projection.on_message(
        message("ba-1", lifecycle="absent", ownerAccountId="usr-owner")
    )
    assert projection.is_ready_billing_account("ba-1", "usr-owner") is False


async def test_a_repeated_event_does_not_change_the_projection() -> None:
    projection = BillingAccountProjection()
    first = message("ba-1", lifecycle="present", ownerAccountId="usr-owner")
    assert await projection.on_message(first) is True
    assert await projection.on_message(first) is False


async def test_other_modules_and_invalid_messages_are_ignored() -> None:
    projection = BillingAccountProjection()
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC).isoformat()
    other = json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000001",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "api",
            "module": "ipm",
            "resourceType": "organization",
            "resourceId": "org-1",
            "operation": "changed",
            "desiredGeneration": 1,
            "requestedBy": "system",
            "correlationId": "01950000-0000-7000-8000-000000000002",
            "occurredAt": now,
            "publishedAt": now,
            "data": {"lifecycle": "present", "ownerAccountId": "usr-1"},
        }
    ).encode()
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{not json") is False
    assert projection.is_ready_billing_account("org-1", "usr-1") is False
