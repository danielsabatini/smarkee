"""Consulta ao Receiver de Organization antes de excluir uma Billing Account."""

from collections.abc import Callable

import httpx
import pytest

from bsm_account.receiver.domain.organizations import OrganizationsCheckError
from bsm_account.receiver.settings import PeersSettings
from bsm_account.receiver.transport.organizations import OrganizationPeer


def peer(handler: Callable[[httpx.Request], httpx.Response]) -> OrganizationPeer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OrganizationPeer(PeersSettings(organizations_url="http://orgs"), client)


async def test_has_organizations_matches_billing_account_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    "not-a-dict",
                    {"resourceId": "o-0", "desired": "not-a-dict"},
                    {"resourceId": "o-1", "desired": {"billingAccountId": "ba-other"}},
                    {"resourceId": "o-2", "desired": {"billingAccountId": "ba-target"}},
                ]
            },
        )

    assert await peer(handler).has_organizations("ba-target", "tok") is True
    assert seen[0].url.path == "/v1/ipm/organizations"
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert await peer(handler).has_organizations("ba-none", "tok") is False


async def test_forbidden_means_ipm_not_enabled_so_no_organizations() -> None:
    empty = peer(lambda r: httpx.Response(403, json={}))
    assert await empty.has_organizations("ba-1", "t") is False


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        (httpx.Response(401, json={}), False),
        (httpx.Response(500, json={}), True),
        (httpx.Response(200, text="bad"), True),
        (httpx.Response(200, json={"items": "bad"}), True),
    ],
)
async def test_inconclusive_answer_raises_error(response: httpx.Response, retryable: bool) -> None:
    with pytest.raises(OrganizationsCheckError) as raised:
        await peer(lambda r: response).has_organizations("ba-1", "tok")
    assert raised.value.retryable is retryable


async def test_network_failure_is_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(OrganizationsCheckError) as raised:
        await peer(boom).has_organizations("ba-1", "tok")
    assert raised.value.retryable is True
