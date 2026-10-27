"""Regras de acesso puras (catálogo e `bind`) e a consulta ao Receiver da Organization."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ipm_serviceaccount.api.domain.access import (
    AccessCheckError,
    OrganizationAccess,
    binding_allowed,
    outside_catalog,
    outside_roles_catalog,
)
from ipm_serviceaccount.api.settings import PeersSettings
from ipm_serviceaccount.api.transport.catalog_consumer import CatalogWatcher
from ipm_serviceaccount.api.transport.organizations import OrganizationPeer
from ipm_serviceaccount.common.catalog import AccessCatalog
from ipm_serviceaccount.common.contracts import generated


def test_outside_catalog_lists_the_refused_permissions_sorted() -> None:
    """O catálogo é o enum `grantablePermission` do contrato (decisão 0081), e não configuração."""
    refused = [
        "ipm.serviceaccount.get",
        "ipm.organization.delete",
        "ipm.serviceaccount.admin",
        "ipm.serviceaccount.admin",
    ]
    assert outside_catalog(refused) == ["ipm.organization.delete", "ipm.serviceaccount.admin"]
    assert outside_catalog([permission.value for permission in generated.GrantablePermission]) == []
    assert outside_catalog([]) == []


def test_binding_without_bind_forbids_any_permission_change() -> None:
    mine = {"ipm.serviceaccount.get", "ipm.serviceaccount.list"}
    assert binding_allowed([], [], mine, can_bind=False)
    assert binding_allowed(
        ["ipm.serviceaccount.get"], ["ipm.serviceaccount.get"], mine, can_bind=False
    )
    assert not binding_allowed([], ["ipm.serviceaccount.get"], mine, can_bind=False)
    assert not binding_allowed([], ["ipm.serviceaccount.bind"], mine, can_bind=False)
    assert not binding_allowed(["ipm.serviceaccount.get"], [], mine, can_bind=False)
    assert not binding_allowed(
        ["ipm.serviceaccount.bind"],
        ["ipm.serviceaccount.bind", "ipm.serviceaccount.get"],
        mine,
        can_bind=False,
    )
    assert binding_allowed([], ["ipm.serviceaccount.bind"], mine, can_bind=True)
    assert binding_allowed([], ["ipm.serviceaccount.get"], mine, can_bind=True)


def peer(handler: Callable[[httpx.Request], httpx.Response]) -> OrganizationPeer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OrganizationPeer(PeersSettings(organizations_url="http://org"), client)


def organization(lifecycle: str) -> dict[str, object]:
    return {"resourceId": "org-1", "desired": {"lifecycle": lifecycle, "name": "acme"}}


async def test_the_owner_is_confirmed_with_the_requester_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=organization("present"))

    assert await peer(handler).access("org-1", "tok") is OrganizationAccess.OWNED
    assert seen[0].url == "http://org/v1/ipm/organizations/org-1"
    assert seen[0].headers["authorization"] == "Bearer tok"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={}),
        httpx.Response(403, json={}),
        httpx.Response(200, json=organization("absent")),
    ],
)
async def test_not_found_forbidden_or_being_removed_is_not_owned(response: httpx.Response) -> None:
    assert await peer(lambda r: response).access("org-1", "tok") is OrganizationAccess.NOT_OWNED


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        (httpx.Response(401, json={}), False),
        (httpx.Response(500, json={}), True),
        (httpx.Response(200, text="não é json"), True),
        (httpx.Response(200, json={"desired": "x"}), True),
    ],
)
async def test_anything_else_is_an_explicit_check_error(
    response: httpx.Response, retryable: bool
) -> None:
    with pytest.raises(AccessCheckError) as raised:
        await peer(lambda r: response).access("org-1", "tok")
    assert raised.value.retryable is retryable


async def test_network_failure_is_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(AccessCheckError) as raised:
        await peer(boom).access("org-1", "tok")
    assert raised.value.retryable


async def test_outside_roles_catalog_and_dynamic_catalog_watcher() -> None:
    catalog = AccessCatalog()
    assert (
        outside_roles_catalog(
            ["ipm.serviceaccountViewer", "ipm.serviceaccountAdmin"],
            organization_id="org-1",
            catalog=catalog,
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
            "permissions": ["ipm.organization.get", "ipm.serviceaccount.get"],
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
        {
            "organizationId": "org-acme",
            "name": "acme.billing",
            "permissions": ["ipm.serviceaccount.get"],
        }
    )
    assert await watcher.on_message(json.dumps(custom_msg).encode()) is True
    assert (
        outside_roles_catalog(["acme.billing"], organization_id="org-acme", catalog=catalog) == []
    )
    assert outside_roles_catalog(
        ["acme.billing"], organization_id="org-other", catalog=catalog
    ) == ["acme.billing"]
    assert catalog.expand_roles(["acme.billing"], "org-acme") == ["ipm.serviceaccount.get"]
    assert catalog.expand_roles(["acme.billing"], "org-other") == []
    assert (
        outside_roles_catalog(
            ["ipm.serviceaccountViewer"], organization_id="org-acme", catalog=catalog
        )
        == []
    )
    custom_msg["data"]["lifecycle"] = "absent"
    assert await watcher.on_message(json.dumps(custom_msg).encode()) is True
    assert outside_roles_catalog(["acme.billing"], organization_id="org-acme", catalog=catalog) == [
        "acme.billing"
    ]
