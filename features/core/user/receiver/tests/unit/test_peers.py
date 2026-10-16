"""Consulta aos outros módulos: só uma listagem válida vale, e na dúvida a exclusão não segue."""

from collections.abc import Callable

import httpx
import pytest

from core_user_receiver.domain.attachments import AttachmentCheckError
from core_user_receiver.settings import PeersSettings
from core_user_receiver.transport.peers import PeerResources

ORGANIZATIONS = "http://org.teste"
SERVICES = "http://sum.teste"


def peers(
    organizations: Callable[[httpx.Request], httpx.Response],
    services: Callable[[httpx.Request], httpx.Response],
    seen: list[httpx.Request] | None = None,
) -> PeerResources:
    def route(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        handler = organizations if request.url.host == "org.teste" else services
        return handler(request)

    settings = PeersSettings(organizations_url=ORGANIZATIONS, services_url=SERVICES)
    return PeerResources(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


def listing(*items: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, json={"items": list(items)})


def link(lifecycle: str) -> dict[str, object]:
    return {"desired": {"lifecycle": lifecycle, "service": "ipm"}}


async def test_nothing_attached_when_both_lists_are_empty() -> None:
    assert await peers(listing(), listing()).of("t") == []


async def test_organizations_and_enabled_services_are_counted_and_history_is_not() -> None:
    found = await peers(
        listing({"resourceId": "a"}, {"resourceId": "b"}),
        listing(link("present"), link("absent")),
    ).of("t")

    assert [item.describe() for item in found] == ["2 Organizations", "1 serviço habilitado"]


async def test_a_disabled_service_alone_does_not_block() -> None:
    assert await peers(listing(), listing(link("absent"))).of("t") == []


async def test_it_sends_only_the_callers_token_to_each_module() -> None:
    seen: list[httpx.Request] = []

    await peers(listing(), listing(), seen).of("token-ana")

    assert {request.headers["authorization"] for request in seen} == {"Bearer token-ana"}
    assert {request.url.path for request in seen} == {"/v1/ipm/organizations", "/v1/sum/services"}


async def test_a_forbidden_answer_of_the_ipm_means_no_organizations_but_not_for_the_sum() -> None:
    """Sem as roles do `ipm` não há como listar; o SUM só deixa desabilitá-lo sem Organizations."""
    forbidden = httpx.Response(403, json={})

    assert await peers(lambda _request: forbidden, listing()).of("t") == []
    with pytest.raises(AttachmentCheckError) as caught:
        await peers(listing(), lambda _request: forbidden).of("t")
    assert (caught.value.module, caught.value.retryable) == ("sum", False)


@pytest.mark.parametrize(("status", "retryable"), [(401, False), (500, True), (503, True)])
async def test_a_refusal_or_failure_is_never_read_as_nothing_attached(
    status: int, retryable: bool
) -> None:
    def refused(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    with pytest.raises(AttachmentCheckError) as caught:
        await peers(refused, listing()).of("t")

    assert caught.value.retryable is retryable
    assert caught.value.module == "ipm"


@pytest.mark.parametrize(
    "response", [httpx.Response(200, text="não é json"), httpx.Response(200, json={"x": 1})]
)
async def test_an_answer_outside_the_contract_is_a_retryable_failure(
    response: httpx.Response,
) -> None:
    with pytest.raises(AttachmentCheckError) as caught:
        await peers(lambda _: response, listing()).of("t")

    assert caught.value.retryable is True


async def test_a_network_failure_is_a_retryable_failure() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(AttachmentCheckError) as caught:
        await peers(boom, listing()).of("t")

    assert caught.value.retryable is True
