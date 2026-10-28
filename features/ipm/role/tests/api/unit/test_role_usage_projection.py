"""Testes da projeção local de uso de Roles (decisão 0100)."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_role.api.transport.role_usage_projection import RoleUsageProjection


def message(resource_id: str, resource_type: str, **data: Any) -> bytes:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=UTC).isoformat()
    return json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000001",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "api",
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


async def test_a_user_group_or_serviceaccount_attaches_and_releases_roles() -> None:
    projection = RoleUsageProjection()

    # Usuário usa role-1 na org-1
    assert await projection.on_message(
        message(
            "u-1", "user", lifecycle="present", organizationId="org-1", roles=["role-1", "role-2"]
        )
    )
    assert projection.is_role_in_use("org-1", "role-1") is True
    assert projection.is_role_in_use("org-1", "role-2") is True
    assert projection.is_role_in_use("org-1", "role-3") is False
    assert projection.is_role_in_use("org-2", "role-1") is False

    # Grupo usa role-1 na org-1 também
    assert await projection.on_message(
        message("g-1", "group", lifecycle="present", organizationId="org-1", roles=["role-1"])
    )
    assert projection.is_role_in_use("org-1", "role-1") is True

    # ServiceAccount usa role-3 na org-1
    assert await projection.on_message(
        message(
            "sa-1",
            "serviceaccount",
            lifecycle="present",
            organizationId="org-1",
            roles=["role-3"],
        )
    )
    assert projection.is_role_in_use("org-1", "role-3") is True

    # Usuário é atualizado: não usa mais role-1, mas ainda usa role-2
    assert await projection.on_message(
        message("u-1", "user", lifecycle="present", organizationId="org-1", roles=["role-2"])
    )
    # role-1 ainda está em uso pelo grupo g-1
    assert projection.is_role_in_use("org-1", "role-1") is True

    # Grupo é removido
    assert await projection.on_message(
        message("g-1", "group", lifecycle="absent", organizationId="org-1", roles=["role-1"])
    )
    # Agora role-1 ficou desocupada
    assert projection.is_role_in_use("org-1", "role-1") is False
    # role-2 continua em uso pelo usuário u-1
    assert projection.is_role_in_use("org-1", "role-2") is True


async def test_repeated_and_irrelevant_messages() -> None:
    projection = RoleUsageProjection()
    msg = message("u-1", "user", lifecycle="present", organizationId="org-1", roles=["role-1"])
    assert await projection.on_message(msg) is True
    assert await projection.on_message(msg) is False

    # Outro tipo ignorado
    other = message(
        "p-1", "permission", lifecycle="present", organizationId="org-1", roles=["role-1"]
    )
    assert await projection.on_message(other) is False
    assert await projection.on_message(b"{invalid") is False
