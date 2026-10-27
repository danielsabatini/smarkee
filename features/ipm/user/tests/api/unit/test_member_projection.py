"""Projeção local do pertencimento de usuários e service accounts (decisão 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_user.api.transport.member_projection import MemberProjection


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


async def test_a_present_user_and_serviceaccount_belong_to_their_organization() -> None:
    projection = MemberProjection()
    assert await projection.on_message(
        message("u-1", "user", lifecycle="present", organizationId="org-1")
    )
    assert await projection.on_message(
        message("sa-1", "serviceaccount", lifecycle="present", organizationId="org-2")
    )
    assert projection.organization_of("u-1") == "org-1"
    assert projection.organization_of("sa-1") == "org-2"
    assert projection.organization_of("unknown") is None


async def test_a_member_being_removed_no_longer_belongs() -> None:
    projection = MemberProjection()
    await projection.on_message(message("u-1", "user", lifecycle="present", organizationId="org-1"))
    assert await projection.on_message(
        message("u-1", "user", lifecycle="absent", organizationId="org-1")
    )
    assert projection.organization_of("u-1") is None


async def test_a_repeated_event_does_not_change_the_projection() -> None:
    projection = MemberProjection()
    first = message("u-1", "user", lifecycle="present", organizationId="org-1")
    assert await projection.on_message(first) is True
    assert await projection.on_message(first) is False


async def test_other_resource_types_and_invalid_messages_are_ignored() -> None:
    projection = MemberProjection()
    other = message("g-1", "group", lifecycle="present", organizationId="org-1")
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{not json") is False
    assert projection.organization_of("g-1") is None
