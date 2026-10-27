"""Consulta aos Receivers de User e ServiceAccount: Organization do solicitante e ocupação."""

from collections.abc import Callable

import httpx
import pytest

from ipm_organization.api.domain.users import BillingAccountCheckError, UsersCheckError
from ipm_organization.api.settings import PeersSettings
from ipm_organization.api.transport.users import UserPeer


def peer(handler: Callable[[httpx.Request], httpx.Response]) -> UserPeer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return UserPeer(
        PeersSettings(
            users_url="http://users",
            serviceaccounts_url="http://machines",
            billing_accounts_url="http://bsm",
        ),
        client,
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


async def test_a_serviceaccount_is_recognized_when_it_is_not_a_user() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "users":
            return httpx.Response(404, json={})
        return httpx.Response(
            200, json={"desired": {"lifecycle": "present", "organizationId": "o-2"}}
        )

    assert await peer(handler).organization_of("machine", "tok") == "o-2"
    assert [r.url.path for r in seen] == [
        "/v1/ipm/users/machine",
        "/v1/ipm/serviceaccounts/machine",
    ]
    assert seen[1].headers["authorization"] == "Bearer tok"


async def test_neither_a_user_nor_a_serviceaccount_is_none() -> None:
    assert await peer(lambda r: httpx.Response(404, json={})).organization_of("x", "tok") is None


async def test_the_organization_with_only_serviceaccounts_is_not_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        items = [{"resourceId": "m-1"}] if request.url.host == "machines" else []
        return httpx.Response(200, json={"items": items})

    assert await peer(handler).has_users("o-1", "tok") is True


async def test_a_serviceaccount_peer_that_does_not_answer_blocks_the_removal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "machines":
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"items": []})

    with pytest.raises(UsersCheckError) as raised:
        await peer(handler).has_users("o-1", "tok")
    assert raised.value.retryable is True


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
