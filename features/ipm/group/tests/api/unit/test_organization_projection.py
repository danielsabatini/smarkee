"""Projeção local das Organizations a partir do `DESIRED` (decisão 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_group.api.domain.access import OrganizationAccess
from ipm_group.api.transport.organization_projection import OrganizationProjection


def message(resource_id: str, *, resource_type: str = "organization", **data: Any) -> bytes:
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


async def test_the_owner_of_a_present_organization_has_access() -> None:
    projection = OrganizationProjection()
    assert await projection.on_message(
        message("org-1", lifecycle="present", ownerAccountId="owner-1")
    )
    assert projection.access("org-1", "owner-1") is OrganizationAccess.OWNED
    assert projection.access("org-1", "someone-else") is OrganizationAccess.NOT_OWNED
    assert projection.access("org-unknown", "owner-1") is OrganizationAccess.NOT_OWNED


async def test_a_removed_organization_loses_its_owner_access() -> None:
    projection = OrganizationProjection()
    await projection.on_message(message("org-1", lifecycle="present", ownerAccountId="owner-1"))
    assert await projection.on_message(
        message("org-1", lifecycle="absent", ownerAccountId="owner-1")
    )
    assert projection.access("org-1", "owner-1") is OrganizationAccess.NOT_OWNED


async def test_a_repeated_event_does_not_change_the_projection() -> None:
    projection = OrganizationProjection()
    first = message("org-1", lifecycle="present", ownerAccountId="owner-1")
    assert await projection.on_message(first) is True
    assert await projection.on_message(first) is False


async def test_other_resource_types_and_invalid_messages_are_ignored() -> None:
    projection = OrganizationProjection()
    other = message("role-1", resource_type="role", lifecycle="present", ownerAccountId="x")
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{not json") is False
    assert projection.access("role-1", "x") is OrganizationAccess.NOT_OWNED
