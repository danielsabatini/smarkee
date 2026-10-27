"""O middleware associa o `traceparent` recebido ao contexto da requisição (decisão 0055)."""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bsm_account.api.http.trace_context import TraceContextMiddleware
from bsm_account.common.logging_config import current_traceparent

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


async def probe(_: Request) -> JSONResponse:
    return JSONResponse({"traceparent": current_traceparent()})


async def call(headers: dict[str, str]) -> str | None:
    app = Starlette(routes=[Route("/", probe)])
    app.add_middleware(TraceContextMiddleware)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        return (await client.get("/", headers=headers)).json()["traceparent"]


async def test_the_header_traceparent_is_the_context_of_the_request() -> None:
    assert await call({"traceparent": TRACEPARENT}) == TRACEPARENT


@pytest.mark.parametrize("value", [None, "garbage", "00-" + "0" * 32 + "-00f067aa0ba902b7-01"])
async def test_a_missing_or_invalid_traceparent_leaves_the_request_without_context(
    value: str | None,
) -> None:
    assert await call({} if value is None else {"traceparent": value}) is None
