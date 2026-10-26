"""Regras de acesso puras (catálogo e `bind`) e a consulta aos Receivers parceiros."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ipm_group.common.catalog import RolesCatalog
from ipm_group.receiver.domain.access import (
    AccessCheckError,
    OrganizationAccess,
    binding_allowed,
    outside_roles_catalog,
)
from ipm_group.receiver.settings import PeersSettings
from ipm_group.receiver.transport.peers import OrganizationPeer, UserPeer


def test_outside_roles_catalog_lists_the_refused_roles_sorted() -> None:
    catalog = RolesCatalog()
    assert outside_roles_catalog(["ipm.userViewer", "ipm.groupAdmin"], catalog=catalog) == []
    assert outside_roles_catalog(
        ["sum.customAdmin", "ipm.unknownRole", "ipm.userViewer"], catalog=catalog
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
    catalog.on_role_desired(role_data)
    assert outside_roles_catalog(["ipm.auditorViewer"], catalog=catalog) == []

    role_data["lifecycle"] = "absent"
    catalog.on_role_desired(role_data)
    assert outside_roles_catalog(["ipm.auditorViewer"], catalog=catalog) == ["ipm.auditorViewer"]


async def test_organization_peer_interprets_status_and_lifecycle() -> None:
    seen_headers: dict[str, str] = {}

    def peer(handler: Callable[[httpx.Request], httpx.Response]) -> OrganizationPeer:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return OrganizationPeer(PeersSettings(), client)

    def ok_present(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"desired": {"lifecycle": "present"}})

    assert await peer(ok_present).access("org-1", "tok") is OrganizationAccess.OWNED
    assert seen_headers["authorization"] == "Bearer tok"

    def ok_absent(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"desired": {"lifecycle": "absent"}})

    assert await peer(ok_absent).access("org-1", "tok") is OrganizationAccess.NOT_OWNED

    def missing(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errorCode": "NotFound", "message": "x"})

    assert await peer(missing).access("org-1", "tok") is OrganizationAccess.NOT_OWNED

    for status, retryable in ((401, False), (503, True)):
        with pytest.raises(AccessCheckError) as raised:
            await peer(lambda _, code=status: httpx.Response(code)).access("org-1", "tok")
        assert raised.value.retryable is retryable


async def test_user_peer_counts_users_with_group_and_reads_organization() -> None:
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
        if request.url.path.endswith("/u-1"):
            return httpx.Response(
                200,
                json={"desired": {"lifecycle": "present", "organizationId": "org-1"}},
            )
        if request.url.path.endswith("/missing"):
            return httpx.Response(404)
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    user_peer = UserPeer(PeersSettings(), client)

    assert await user_peer.count_users_with_group("org-1", "auditors", "tok") == 2
    assert await user_peer.get_user_organization("u-1", "tok") == "org-1"
    assert await user_peer.get_user_organization("missing", "tok") is None
