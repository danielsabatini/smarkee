"""Testes da projeção local de uso de Grupos por usuários (decisão 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_group.api.transport.group_usage_projection import GroupUsageProjection


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


async def test_users_attach_and_detach_from_groups() -> None:
    projection = GroupUsageProjection()

    # u-1 na org-1 entra nos grupos dev e ops
    assert await projection.on_message(
        message("u-1", "user", lifecycle="present", organizationId="org-1", groups=["dev", "ops"])
    )
    assert projection.count_users_with_group("org-1", "dev") == 1
    assert projection.count_users_with_group("org-1", "ops") == 1
    assert projection.count_users_with_group("org-1", "qa") == 0
    assert projection.count_users_with_group("org-2", "dev") == 0

    # u-2 na org-1 entra no grupo dev
    assert await projection.on_message(
        message("u-2", "user", lifecycle="present", organizationId="org-1", groups=["dev"])
    )
    assert projection.count_users_with_group("org-1", "dev") == 2

    # u-1 atualiza grupos: sai de dev, fica em ops
    assert await projection.on_message(
        message("u-1", "user", lifecycle="present", organizationId="org-1", groups=["ops"])
    )
    assert projection.count_users_with_group("org-1", "dev") == 1
    assert projection.count_users_with_group("org-1", "ops") == 1

    # u-2 é removido
    assert await projection.on_message(
        message("u-2", "user", lifecycle="absent", organizationId="org-1", groups=["dev"])
    )
    assert projection.count_users_with_group("org-1", "dev") == 0
    assert projection.count_users_with_group("org-1", "ops") == 1


async def test_repeated_and_irrelevant_messages() -> None:
    projection = GroupUsageProjection()
    msg = message("u-1", "user", lifecycle="present", organizationId="org-1", groups=["dev"])
    assert await projection.on_message(msg) is True
    assert await projection.on_message(msg) is False

    # Outro tipo ignorado
    other = message(
        "sa-1", "serviceaccount", lifecycle="present", organizationId="org-1", groups=["dev"]
    )
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{invalid") is False
