"""Consulta ao Receiver do User: a Organization do solicitante e se ela ainda tem usuários."""

from collections.abc import Callable

import httpx
import pytest

from ipm_organization.receiver.domain.users import BillingAccountCheckError, UsersCheckError
from ipm_organization.receiver.settings import PeersSettings
from ipm_organization.receiver.transport.users import UserPeer


def peer(handler: Callable[[httpx.Request], httpx.Response]) -> UserPeer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UserPeer(
        PeersSettings(users_url="http://users", billing_accounts_url="http://bsm"), client
    )


async def test_the_own_record_gives_the_organization_with_the_requester_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"desired": {"lifecycle": "present", "organizationId": "o-1"}}
        )

    assert await peer(handler).organization_of("bia", "tok") == "o-1"
    assert seen[0].url.path == "/v1/ipm/users/bia"
    assert seen[0].headers["authorization"] == "Bearer tok"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={}),
        httpx.Response(200, json={"desired": {"lifecycle": "absent", "organizationId": "o-1"}}),
    ],
)
async def test_not_a_user_or_being_removed_is_none(response: httpx.Response) -> None:
    assert await peer(lambda r: response).organization_of("bia", "tok") is None


async def test_has_users_asks_one_item_of_the_organization() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": [{"resourceId": "u-1"}]})

    assert await peer(handler).has_users("o-1", "tok") is True
    assert dict(seen[0].url.params) == {"organizationId": "o-1", "limit": "1"}
    empty = peer(lambda r: httpx.Response(200, json={"items": []}))
    assert await empty.has_users("o-1", "tok") is False


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        (httpx.Response(404, json={}), False),
        (httpx.Response(403, json={}), False),
        (httpx.Response(401, json={}), False),
        (httpx.Response(500, json={}), True),
        (httpx.Response(200, text="não é json"), True),
        (httpx.Response(200, json={"items": "x"}), True),
    ],
)
async def test_an_inconclusive_answer_is_an_explicit_error(
    response: httpx.Response, retryable: bool
) -> None:
    with pytest.raises(UsersCheckError) as raised:
        await peer(lambda r: response).has_users("o-1", "tok")
    assert raised.value.retryable is retryable


async def test_network_failure_is_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(UsersCheckError) as raised:
        await peer(boom).organization_of("bia", "tok")
    assert raised.value.retryable


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
