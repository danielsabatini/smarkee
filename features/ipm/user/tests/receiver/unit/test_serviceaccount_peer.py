"""Consulta ao Receiver de ServiceAccount: a Organization da identidade de máquina (0094)."""

from collections.abc import Callable

import httpx
import pytest

from ipm_user.receiver.settings import PeersSettings
from ipm_user.receiver.transport.serviceaccounts import ServiceAccountPeer


def peer(handler: Callable[[httpx.Request], httpx.Response]) -> ServiceAccountPeer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ServiceAccountPeer(PeersSettings(serviceaccounts_url="http://machines"), client)


async def test_the_own_record_gives_the_organization_with_the_requester_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"desired": {"lifecycle": "present", "organizationId": "o-1"}}
        )

    assert await peer(handler).get_serviceaccount_organization("m-1", "tok") == "o-1"
    assert seen[0].url.path == "/v1/ipm/serviceaccounts/m-1"
    assert seen[0].headers["authorization"] == "Bearer tok"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={}),
        httpx.Response(503, json={}),
        httpx.Response(200, text="não é json"),
        httpx.Response(200, json=["x"]),
        httpx.Response(200, json={"desired": "x"}),
        httpx.Response(200, json={"desired": {"lifecycle": "absent", "organizationId": "o-1"}}),
        httpx.Response(200, json={"desired": {"lifecycle": "present"}}),
    ],
)
async def test_anything_but_a_present_serviceaccount_is_none(response: httpx.Response) -> None:
    assert await peer(lambda r: response).get_serviceaccount_organization("m-1", "tok") is None


async def test_network_failure_is_none() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert await peer(boom).get_serviceaccount_organization("m-1", "tok") is None
