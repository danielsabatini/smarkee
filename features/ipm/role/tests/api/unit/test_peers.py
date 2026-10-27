"""Consulta do Receiver de Role aos Receivers parceiros (decisões 0092 e 0094)."""

import httpx
import pytest

from ipm_role.api.domain.access import AccessCheckError
from ipm_role.api.settings import PeersSettings
from ipm_role.api.transport.peers import RoleUsagePeer, UserPeer


async def test_user_peer_reads_the_organization_of_a_present_serviceaccount() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/v1/ipm/serviceaccounts/")
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "machine-1":
            return httpx.Response(
                200, json={"desired": {"lifecycle": "present", "organizationId": "org-1"}}
            )
        if name == "removed":
            return httpx.Response(
                200, json={"desired": {"lifecycle": "absent", "organizationId": "org-1"}}
            )
        return httpx.Response(404)

    peer = UserPeer(PeersSettings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    assert await peer.get_serviceaccount_organization("machine-1", "tok") == "org-1"
    assert await peer.get_serviceaccount_organization("removed", "tok") is None
    assert await peer.get_serviceaccount_organization("missing", "tok") is None


async def test_role_in_use_looks_at_serviceaccounts_too() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/ipm/serviceaccounts":
            return httpx.Response(
                200,
                json={"items": [{"desired": {"lifecycle": "present", "roles": ["custom.deploy"]}}]},
            )
        return httpx.Response(200, json={"items": []})

    peer = RoleUsagePeer(PeersSettings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    assert await peer.role_in_use("org-1", "custom.deploy", "tok") is True
    assert await peer.role_in_use("org-1", "custom.other", "tok") is False


async def test_role_in_use_fails_closed_when_the_serviceaccount_peer_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/ipm/serviceaccounts":
            return httpx.Response(503)
        return httpx.Response(200, json={"items": []})

    peer = RoleUsagePeer(PeersSettings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(AccessCheckError) as raised:
        await peer.role_in_use("org-1", "custom.deploy", "tok")
    assert raised.value.retryable is True
