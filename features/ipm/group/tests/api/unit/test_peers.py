"""Regras de acesso puras (catálogo e `bind`) e a consulta aos Receivers parceiros."""

from typing import Any

import httpx

from ipm_group.api.domain.access import (
    binding_allowed,
    outside_roles_catalog,
)
from ipm_group.api.settings import PeersSettings
from ipm_group.api.transport.peers import UserPeer
from ipm_group.common.catalog import RolesCatalog


def test_outside_roles_catalog_lists_the_refused_roles_sorted() -> None:
    catalog = RolesCatalog()
    assert (
        outside_roles_catalog(
            ["ipm.userViewer", "ipm.groupAdmin"], organization_id="org-1", catalog=catalog
        )
        == []
    )
    assert outside_roles_catalog(
        ["sum.customAdmin", "ipm.unknownRole", "ipm.userViewer"],
        organization_id="org-1",
        catalog=catalog,
    ) == ["ipm.unknownRole", "sum.customAdmin"]


def test_binding_allowed_requires_can_bind_when_roles_change() -> None:
    assert binding_allowed(
        ["ipm.userViewer"], ["ipm.userViewer"], ["ipm.group.update"], can_bind=False
    )
    assert not binding_allowed([], ["ipm.userViewer"], ["ipm.group.create"], can_bind=False)
    assert binding_allowed(
        [], ["ipm.userViewer"], ["ipm.group.create", "ipm.group.bind"], can_bind=True
    )


def test_roles_catalog_updates_from_desired_messages() -> None:
    catalog = RolesCatalog({"ipm.userViewer": ["ipm.user.get"]})
    role_data: dict[str, Any] = {
        "lifecycle": "present",
        "reconciliation": "active",
        "name": "ipm.auditorViewer",
        "description": "Auditor da Organization",
        "permissions": ["ipm.organization.get", "ipm.user.get"],
        "deletionProtection": False,
    }
    assert catalog.apply_role_desired("role-1", role_data)
    assert (
        outside_roles_catalog(["ipm.auditorViewer"], organization_id="org-1", catalog=catalog) == []
    )

    role_data["lifecycle"] = "absent"
    assert catalog.apply_role_desired("role-1", role_data)
    assert outside_roles_catalog(
        ["ipm.auditorViewer"], organization_id="org-1", catalog=catalog
    ) == ["ipm.auditorViewer"]


def test_custom_role_is_visible_only_in_its_organization() -> None:
    """Decisão 0092: `custom` vale só na Organization dona; as predefinidas valem em todas."""
    catalog = RolesCatalog({"ipm.userViewer": ["ipm.user.get"]})
    custom: dict[str, Any] = {
        "lifecycle": "present",
        "organizationId": "org-acme",
        "name": "acme.billing",
        "permissions": ["ipm.user.get"],
    }
    assert catalog.apply_role_desired("role-acme", custom)
    assert (
        outside_roles_catalog(["acme.billing"], organization_id="org-acme", catalog=catalog) == []
    )
    assert outside_roles_catalog(
        ["acme.billing"], organization_id="org-other", catalog=catalog
    ) == ["acme.billing"]
    assert (
        outside_roles_catalog(["ipm.userViewer"], organization_id="org-other", catalog=catalog)
        == []
    )
    # Mensagem sem `name` (ex.: remoção) usa a chave guardada pelo `resourceId`.
    assert catalog.apply_role_desired("role-acme", {"lifecycle": "absent"})
    assert outside_roles_catalog(["acme.billing"], organization_id="org-acme", catalog=catalog) == [
        "acme.billing"
    ]


async def test_user_peer_counts_users_with_group() -> None:
    payload: dict[str, Any] = {
        "items": [
            {
                "resourceId": "u-1",
                "desired": {"lifecycle": "present", "groups": ["auditors", "viewers"]},
            },
            {
                "resourceId": "u-2",
                "desired": {"lifecycle": "present", "groups": ["viewers"]},
            },
            {
                "resourceId": "u-3",
                "desired": {"lifecycle": "present", "groups": ["auditors"]},
            },
            {
                "resourceId": "u-4",
                "desired": {"lifecycle": "absent", "groups": ["auditors"]},
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    user_peer = UserPeer(PeersSettings(), client)

    assert await user_peer.count_users_with_group("org-1", "auditors", "tok") == 2
