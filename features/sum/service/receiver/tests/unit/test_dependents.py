"""O que depende de um serviço: só uma listagem válida vale, e na dúvida desabilitar não segue."""

import httpx
import pytest

from sum_service_receiver.domain.dependents import DependentsCheckError
from sum_service_receiver.settings import PeersSettings
from sum_service_receiver.transport.dependents import PeerDependents


def dependents(
    response: httpx.Response | None = None, seen: list[httpx.Request] | None = None
) -> PeerDependents:
    def route(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return response or httpx.Response(200, json={"items": []})

    settings = PeersSettings(organizations_url="http://org.teste")
    return PeerDependents(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


async def test_a_service_without_dependents_is_not_even_asked() -> None:
    seen: list[httpx.Request] = []

    assert await dependents(seen=seen).count("outro", "t") == 0
    assert seen == []


async def test_the_organizations_of_the_caller_are_the_dependents_of_the_ipm() -> None:
    seen: list[httpx.Request] = []
    two = httpx.Response(200, json={"items": [{"resourceId": "a"}, {"resourceId": "b"}]})

    assert await dependents(two, seen).count("ipm", "token-ana") == 2
    assert seen[0].url.path == "/v1/ipm/organizations"
    assert seen[0].headers["authorization"] == "Bearer token-ana"


async def test_no_organization_means_no_dependents() -> None:
    assert await dependents().count("ipm", "t") == 0


@pytest.mark.parametrize(
    ("status", "retryable"), [(401, False), (403, False), (500, True), (503, True)]
)
async def test_a_refusal_or_failure_is_never_read_as_no_dependents(
    status: int, retryable: bool
) -> None:
    with pytest.raises(DependentsCheckError) as caught:
        await dependents(httpx.Response(status, json={})).count("ipm", "t")

    assert caught.value.retryable is retryable


@pytest.mark.parametrize(
    "response", [httpx.Response(200, text="não é json"), httpx.Response(200, json={"x": 1})]
)
async def test_an_answer_outside_the_contract_is_a_retryable_failure(
    response: httpx.Response,
) -> None:
    with pytest.raises(DependentsCheckError) as caught:
        await dependents(response).count("ipm", "t")

    assert caught.value.retryable is True


async def test_a_network_failure_is_a_retryable_failure() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    settings = PeersSettings(organizations_url="http://org.teste")
    peer = PeerDependents(settings, httpx.AsyncClient(transport=httpx.MockTransport(boom)))

    with pytest.raises(DependentsCheckError) as caught:
        await peer.count("ipm", "t")

    assert caught.value.retryable is True
