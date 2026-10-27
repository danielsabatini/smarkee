"""Consulta ao Receiver de Billing Account: confirmação de prontidão (decisão 0082)."""

from collections.abc import Callable

import httpx
import pytest

from ipm_organization.api.domain.users import BillingAccountCheckError
from ipm_organization.api.settings import PeersSettings
from ipm_organization.api.transport.billing_accounts import BillingAccountPeer


def peer(handler: Callable[[httpx.Request], httpx.Response]) -> BillingAccountPeer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BillingAccountPeer(
        PeersSettings(
            billing_accounts_url="http://bsm",
        ),
        client,
    )


async def test_is_ready_billing_account_checks_get_endpoint_with_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"phase": "Ready", "desired": {"lifecycle": "present"}})

    assert await peer(handler).is_ready_billing_account("ba-1", "tok") is True
    assert seen[0].url.host == "bsm"
    assert seen[0].url.path == "/v1/bsm/accounts/ba-1"
    assert seen[0].headers["authorization"] == "Bearer tok"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={}),
        httpx.Response(200, json={"phase": "Pending", "desired": {"lifecycle": "present"}}),
        httpx.Response(200, json={"phase": "Deleting", "desired": {"lifecycle": "absent"}}),
    ],
)
async def test_missing_or_unready_billing_account_returns_false(response: httpx.Response) -> None:
    assert await peer(lambda r: response).is_ready_billing_account("ba-1", "tok") is False


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        (httpx.Response(401, json={}), False),
        (httpx.Response(403, json={}), False),
        (httpx.Response(500, json={}), True),
        (httpx.Response(200, text="bad"), True),
        (httpx.Response(200, json=["not-a-dict"]), True),
        (httpx.Response(200, json={"phase": "Ready", "desired": "not-a-dict"}), True),
    ],
)
async def test_billing_account_inconclusive_answer_raises_error(
    response: httpx.Response, retryable: bool
) -> None:
    with pytest.raises(BillingAccountCheckError) as raised:
        await peer(lambda r: response).is_ready_billing_account("ba-1", "tok")
    assert raised.value.retryable is retryable


async def test_billing_account_network_failure_is_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(BillingAccountCheckError) as raised:
        await peer(boom).is_ready_billing_account("ba-1", "tok")
    assert raised.value.retryable is True
