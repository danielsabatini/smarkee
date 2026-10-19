"""Token da conta de serviço do Zitadel: assertion JWT, cache e falhas (decisão 0063)."""

import json
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ipm_organization.common.zitadel import ServiceAccountToken, TokenError, ZitadelSettings


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"userId": "svc-1", "keyId": "key-1", "key": pem}))
    return path


class Zitadel:
    """Endpoint de token simulado; guarda as chamadas recebidas."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or httpx.Response(
            200, json={"access_token": "tok", "expires_in": 3600}
        )
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def source(
    key_file: Path, zitadel: Zitadel, clock: list[float] | None = None
) -> ServiceAccountToken:
    now = clock if clock is not None else [1000.0]
    return ServiceAccountToken(
        ZitadelSettings(key_file=str(key_file), base_url="http://z"),
        httpx.AsyncClient(transport=httpx.MockTransport(zitadel.handler)),
        clock=lambda: now[0],
    )


async def test_it_trades_a_signed_assertion_for_a_token_and_sends_the_host_header(
    key_file: Path,
) -> None:
    zitadel = Zitadel()
    assert await source(key_file, zitadel).get() == "tok"

    request = zitadel.requests[0]
    assert request.url == "http://z/oauth/v2/token"
    assert request.headers["host"] == "ipm-dev.smarkee.com.br:8080"
    form = dict(item.split("=") for item in request.content.decode().split("&"))
    assert form["grant_type"].startswith("urn%3Aietf")
    claims = jwt.decode(form["assertion"], options={"verify_signature": False})
    assert (claims["iss"], claims["sub"]) == ("svc-1", "svc-1")
    assert claims["aud"] == "http://ipm-dev.smarkee.com.br:8080"
    assert (claims["iat"], claims["exp"]) == (1000, 1300)
    assert jwt.get_unverified_header(form["assertion"])["kid"] == "key-1"


async def test_the_token_is_reused_until_a_minute_before_it_expires(key_file: Path) -> None:
    zitadel = Zitadel()
    clock = [1000.0]
    tokens = source(key_file, zitadel, clock)
    await tokens.get()
    clock[0] = 1000.0 + 3600 - 61
    await tokens.get()
    assert len(zitadel.requests) == 1
    clock[0] = 1000.0 + 3600 - 59
    await tokens.get()
    assert len(zitadel.requests) == 2


@pytest.mark.parametrize("content", [None, "não é json", "{}", '{"userId": "u", "keyId": "k"}'])
async def test_an_unusable_key_file_is_a_key_error_without_leaking_its_content(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "key.json"
    if content is not None:
        path.write_text(content)
    tokens = source(path, Zitadel())
    with pytest.raises(TokenError) as raised:
        await tokens.get()
    assert raised.value.kind == "key"
    assert raised.value.detail.startswith("key unavailable: ")
    assert "não é json" not in raised.value.detail


FAILED_EXCHANGES = [
    httpx.Response(500),
    httpx.Response(401, json={"error": "invalid_client"}),
    httpx.Response(200),  # sem corpo JSON
]


@pytest.mark.parametrize("response", FAILED_EXCHANGES)
async def test_a_failed_exchange_is_an_exchange_error(
    key_file: Path, response: httpx.Response
) -> None:
    with pytest.raises(TokenError) as raised:
        await source(key_file, Zitadel(response)).get()
    assert raised.value.kind == "exchange"
    assert raised.value.detail.startswith("token: ")
