"""Testes da projeção local de uso de Billing Accounts por Organizations (decisões 0082 e 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from bsm_account.api.transport.organization_usage_projection import OrganizationUsageProjection


def message(resource_id: str, resource_type: str, **data: Any) -> bytes:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC).isoformat()
    return json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000001",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "manager",
            "module": "ipm",
            "resourceType": resource_type,
            "resourceId": resource_id,
            "operation": "changed",
            "desiredGeneration": 1,
            "requestedBy": "system",
            "correlationId": "01950000-0000-7000-8000-000000000002",
            "causationId": "01950000-0000-7000-8000-000000000003",
            "occurredAt": now,
            "publishedAt": now,
            "data": data,
        }
    ).encode()


async def test_organizations_attach_and_detach_from_billing_accounts() -> None:
    projection = OrganizationUsageProjection()

    # org-1 vincula-se a ba-1
    assert await projection.on_message(
        message("org-1", "organization", lifecycle="present", billingAccountId="ba-1")
    )
    assert projection.has_attached_organizations("ba-1") is True
    assert projection.has_attached_organizations("ba-2") is False

    # org-2 vincula-se a ba-1
    assert await projection.on_message(
        message("org-2", "organization", lifecycle="present", billingAccountId="ba-1")
    )
    assert projection.has_attached_organizations("ba-1") is True

    # org-1 muda para ba-2
    assert await projection.on_message(
        message("org-1", "organization", lifecycle="present", billingAccountId="ba-2")
    )
    assert projection.has_attached_organizations("ba-1") is True
    assert projection.has_attached_organizations("ba-2") is True

    # org-2 é removida (absent)
    assert await projection.on_message(
        message("org-2", "organization", lifecycle="absent", billingAccountId="ba-1")
    )
    assert projection.has_attached_organizations("ba-1") is False
    assert projection.has_attached_organizations("ba-2") is True


async def test_repeated_and_irrelevant_messages() -> None:
    projection = OrganizationUsageProjection()
    msg = message("org-1", "organization", lifecycle="present", billingAccountId="ba-1")
    assert await projection.on_message(msg) is True
    assert await projection.on_message(msg) is False

    # Outro tipo ignorado
    other = message("user-1", "user", lifecycle="present", billingAccountId="ba-1")
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{invalid") is False
