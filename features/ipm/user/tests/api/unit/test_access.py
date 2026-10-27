"""Regras de acesso puras (catálogo e `bind`) e a consulta ao Receiver da Organization."""

import json
from datetime import UTC, datetime
from typing import Any

from ipm_user.api.domain.access import (
    binding_allowed,
    outside_catalog,
    outside_groups_catalog,
    outside_roles_catalog,
)
from ipm_user.api.transport.catalog_consumer import CatalogWatcher
from ipm_user.common.catalog import AccessCatalog
from ipm_user.common.contracts import generated


def test_outside_catalog_lists_the_refused_permissions_sorted() -> None:
    """O catálogo é o enum `grantablePermission` do contrato (decisão 0081), e não configuração."""
    refused = ["ipm.user.get", "ipm.organization.delete", "ipm.user.admin", "ipm.user.admin"]
    assert outside_catalog(refused) == ["ipm.organization.delete", "ipm.user.admin"]
    assert outside_catalog([permission.value for permission in generated.GrantablePermission]) == []
    assert outside_catalog([]) == []


def test_outside_groups_catalog_detects_unknown_groups() -> None:
    catalog = AccessCatalog()
    catalog.apply_group_desired(
        "grp-1",
        {
            "lifecycle": "present",
            "organizationId": "org-1",
            "name": "devs",
            "roles": ["ipm.userViewer"],
        },
    )
    assert outside_groups_catalog(["devs"], organization_id="org-1", catalog=catalog) == []
    assert outside_groups_catalog(
        ["devs", "unknown", "other"], organization_id="org-1", catalog=catalog
    ) == [
        "other",
        "unknown",
    ]
    # Em outra organization, o grupo 'devs' não existe
    assert outside_groups_catalog(["devs"], organization_id="org-2", catalog=catalog) == ["devs"]


def test_binding_without_bind_forbids_any_permission_change() -> None:
    mine = {"ipm.user.get", "ipm.user.list"}
    assert binding_allowed([], [], mine, can_bind=False)
    assert binding_allowed(["ipm.user.get"], ["ipm.user.get"], mine, can_bind=False)
    assert not binding_allowed([], ["ipm.user.get"], mine, can_bind=False)
    assert not binding_allowed([], ["ipm.user.bind"], mine, can_bind=False)
    assert not binding_allowed(["ipm.user.get"], [], mine, can_bind=False)
    assert not binding_allowed(
        ["ipm.user.bind"], ["ipm.user.bind", "ipm.user.get"], mine, can_bind=False
    )
    assert binding_allowed([], ["ipm.user.bind"], mine, can_bind=True)
    assert binding_allowed([], ["ipm.user.get"], mine, can_bind=True)


async def test_outside_roles_catalog_and_dynamic_catalog_watcher() -> None:
    catalog = AccessCatalog()
    assert (
        outside_roles_catalog(
            ["ipm.userViewer", "ipm.userAdmin"], organization_id="org-1", catalog=catalog
        )
        == []
    )
    assert outside_roles_catalog(
        ["core.accountAdmin", "ipm.permissionAdmin", "ipm.unknownRole"],
        organization_id="org-1",
        catalog=catalog,
    ) == ["core.accountAdmin", "ipm.permissionAdmin", "ipm.unknownRole"]

    watcher = CatalogWatcher(catalog)
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC).isoformat()
    role_msg: dict[str, Any] = {
        "messageId": "01950000-0000-7000-8000-000000000001",
        "schemaVersion": "1.0",
        "messageType": "desired",
        "emitter": "manager",
        "module": "ipm",
        "resourceType": "role",
        "resourceId": "role-ipm-auditor",
        "operation": "changed",
        "desiredGeneration": 1,
        "requestedBy": "system",
        "correlationId": "01950000-0000-7000-8000-000000000002",
        "causationId": "01950000-0000-7000-8000-000000000003",
        "occurredAt": now,
        "publishedAt": now,
        "data": {
            "lifecycle": "present",
            "reconciliation": "active",
            "name": "ipm.auditorViewer",
            "description": "Auditor da Organization",
            "permissions": ["ipm.organization.get", "ipm.user.get"],
            "deletionProtection": False,
        },
    }
    assert await watcher.on_message(json.dumps(role_msg).encode()) is True
    assert (
        outside_roles_catalog(["ipm.auditorViewer"], organization_id="org-1", catalog=catalog) == []
    )

    # Role `custom` (decisão 0092): só vale na Organization dona; as predefinidas valem em todas.
    custom_msg = json.loads(json.dumps(role_msg))
    custom_msg["resourceId"] = "role-acme-billing"
    custom_msg["data"].update(
        {"organizationId": "org-acme", "name": "acme.billing", "permissions": ["ipm.user.get"]}
    )
    assert await watcher.on_message(json.dumps(custom_msg).encode()) is True
    assert (
        outside_roles_catalog(["acme.billing"], organization_id="org-acme", catalog=catalog) == []
    )
    assert outside_roles_catalog(
        ["acme.billing"], organization_id="org-other", catalog=catalog
    ) == ["acme.billing"]
    assert catalog.expand_roles(["acme.billing"], "org-acme") == ["ipm.user.get"]
    assert catalog.expand_roles(["acme.billing"], "org-other") == []
    assert (
        outside_roles_catalog(["ipm.userViewer"], organization_id="org-acme", catalog=catalog) == []
    )
    custom_msg["data"]["lifecycle"] = "absent"
    assert await watcher.on_message(json.dumps(custom_msg).encode()) is True
    assert outside_roles_catalog(["acme.billing"], organization_id="org-acme", catalog=catalog) == [
        "acme.billing"
    ]
