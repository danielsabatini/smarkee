"""Regras de acesso puras (catálogo e `bind`) e a consulta ao Receiver da Organization."""

from collections.abc import Callable

import httpx
import pytest

from ipm_user.common.contracts import generated
from ipm_user.receiver.domain.access import (
    AccessCheckError,
    OrganizationAccess,
    binding_allowed,
    outside_catalog,
)
from ipm_user.receiver.settings import PeersSettings
from ipm_user.receiver.transport.organizations import OrganizationPeer


def test_outside_catalog_lists_the_refused_roles_sorted() -> None:
    """O catálogo é o enum `grantableRole` do contrato (decisão 0081), e não configuração."""
    refused = ["ipm.user.get", "ipm.organization.delete", "ipm.user.admin", "ipm.user.admin"]
    assert outside_catalog(refused) == ["ipm.organization.delete", "ipm.user.admin"]
    assert outside_catalog([role.value for role in generated.GrantableRole]) == []
    assert outside_catalog([]) == []


def test_binding_without_bind_only_touches_roles_the_requester_has() -> None:
    mine = {"ipm.user.get", "ipm.user.list"}
    assert binding_allowed([], ["ipm.user.get"], mine, can_bind=False)
    assert not binding_allowed([], ["ipm.user.bind"], mine, can_bind=False)
    # Retirar uma role que quem pede não tem também exige `bind`.
    assert not binding_allowed(["ipm.user.bind"], [], mine, can_bind=False)
    # Manter uma role alheia sem mexer nela é permitido.
    assert binding_allowed(
        ["ipm.user.bind"], ["ipm.user.bind", "ipm.user.get"], mine, can_bind=False
    )
    assert binding_allowed([], ["ipm.user.bind"], mine, can_bind=True)


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
