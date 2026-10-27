"""Projeções locais dos recursos atrelados à conta (decisões 0040 e 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from core_account.api.transport.attached_projection import (
    BILLING_ACCOUNTS,
    ORGANIZATIONS,
    SERVICES,
    AttachedProjection,
    AttachedResources,
)


def message(module: str, resource_type: str, resource_id: str, **data: Any) -> bytes:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC).isoformat()
    return json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000001",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "api",
            "module": module,
            "resourceType": resource_type,
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


async def test_a_resource_belongs_to_the_account_while_it_is_present() -> None:
    projection = AttachedProjection(ORGANIZATIONS)
    present = message("ipm", "organization", "org-1", lifecycle="present", ownerAccountId="acc-1")

    assert await projection.on_message(present) is True
    assert await projection.on_message(present) is False  # repetição não muda nada
    assert projection.count("acc-1") == 1 and projection.count("acc-2") == 0

    absent = message("ipm", "organization", "org-1", lifecycle="absent", ownerAccountId="acc-1")
    assert await projection.on_message(absent) is True
    assert projection.count("acc-1") == 0


async def test_other_types_and_invalid_messages_are_ignored() -> None:
    projection = AttachedProjection(ORGANIZATIONS)
    other = message("ipm", "user", "u-1", lifecycle="present", ownerAccountId="acc-1")
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{invalido") is False
    assert projection.count("acc-1") == 0


async def test_the_resources_sum_every_projection_and_describe_the_plural() -> None:
    organizations = AttachedProjection(ORGANIZATIONS)
    billing = AttachedProjection(BILLING_ACCOUNTS)
    services = AttachedProjection(SERVICES)
    for resource_id in ("org-1", "org-2"):
        await organizations.on_message(
            message("ipm", "organization", resource_id, lifecycle="present", ownerAccountId="acc-1")
        )
    await billing.on_message(
        message("bsm", "account", "ba-1", lifecycle="present", ownerAccountId="acc-1")
    )

    found = AttachedResources([organizations, billing, services]).of("acc-1")

    assert [item.describe() for item in found] == ["2 Organizations", "1 Billing Account"]
    assert AttachedResources([organizations, billing, services]).of("acc-9") == []
