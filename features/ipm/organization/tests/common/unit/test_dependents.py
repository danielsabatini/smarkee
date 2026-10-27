"""Testes da projeção local de dependentes da Organization (decisões 0077, 0094 e 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_organization.common.dependents import DependentsProjection


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


async def test_dependents_track_active_resources_in_organizations() -> None:
    projection = DependentsProjection()

    # Adiciona user na org-1
    assert await projection.on_message(
        message("u-1", "user", lifecycle="present", organizationId="org-1")
    )
    assert projection.has_dependents("org-1") is True
    assert projection.count_dependents("org-1") == 1
    assert projection.has_dependents("org-2") is False

    # Adiciona serviceaccount, group e role na org-1
    assert await projection.on_message(
        message("sa-1", "serviceaccount", lifecycle="present", organizationId="org-1")
    )
    assert await projection.on_message(
        message("g-1", "group", lifecycle="present", organizationId="org-1")
    )
    assert await projection.on_message(
        message("r-1", "role", lifecycle="present", organizationId="org-1")
    )
    assert projection.count_dependents("org-1") == 4

    # u-1 vai para absent
    assert await projection.on_message(
        message("u-1", "user", lifecycle="absent", organizationId="org-1")
    )
    assert projection.count_dependents("org-1") == 3

    # Remove os outros 3
    await projection.on_message(
        message("sa-1", "serviceaccount", lifecycle="absent", organizationId="org-1")
    )
    await projection.on_message(message("g-1", "group", lifecycle="absent", organizationId="org-1"))
    await projection.on_message(message("r-1", "role", lifecycle="absent", organizationId="org-1"))
    assert projection.has_dependents("org-1") is False
    assert projection.count_dependents("org-1") == 0


async def test_repeated_and_irrelevant_messages() -> None:
    projection = DependentsProjection()
    msg = message("u-1", "user", lifecycle="present", organizationId="org-1")
    assert await projection.on_message(msg) is True
    assert await projection.on_message(msg) is False

    # Outro tipo ignorado
    other = message("p-1", "permission", lifecycle="present", organizationId="org-1")
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{invalid") is False
