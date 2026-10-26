"""Driver de leitura do metadado: filtro pela chave, valor decodificado e falha como erro."""

import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ipm_serviceaccount.observer.domain.identity import ProviderError
from ipm_serviceaccount.observer.drivers.metadata import MetadataDriver, Owner
from ipm_serviceaccount.observer.provider.identity import IdentityConnection
from ipm_serviceaccount.observer.settings import IdentitySettings


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


def driver(
    key_file: Path,
    owner: Owner,
    handler: Callable[[httpx.Request], httpx.Response],
    calls: list[httpx.Request] | None = None,
) -> MetadataDriver:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if calls is not None:
            calls.append(request)
        return handler(request)

    settings = IdentitySettings(key_file=str(key_file), base_url="http://z")
    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return MetadataDriver(IdentityConnection(settings, client), owner)


def entry(key: str, value: bytes) -> dict[str, str]:
    return {"key": key, "value": base64.b64encode(value).decode()}


@pytest.mark.parametrize("owner", ["organizations", "users"])
async def test_get_value_filters_by_key_and_decodes_the_value(key_file: Path, owner: Owner) -> None:
    calls: list[httpx.Request] = []
    found = {"metadata": [entry("deletionProtection", b"false")]}
    metadata = driver(key_file, owner, lambda _r: httpx.Response(200, json=found), calls)

    assert await metadata.get_value("r-1", "deletionProtection") == "false"

    (request,) = calls
    assert (request.method, request.url.path) == ("POST", f"/v2/{owner}/r-1/metadata/search")
    assert json.loads(request.content) == {
        "filters": [{"keyFilter": {"key": "deletionProtection"}}]
    }


async def test_a_missing_key_is_none(key_file: Path) -> None:
    empty: dict[str, object] = {"pagination": {}}
    metadata = driver(key_file, "organizations", lambda _r: httpx.Response(200, json=empty))
    assert await metadata.get_value("r-1", "deletionProtection") is None


async def test_another_key_in_the_answer_is_ignored(key_file: Path) -> None:
    other = {"metadata": [entry("outra", b"true")]}
    metadata = driver(key_file, "users", lambda _r: httpx.Response(200, json=other))
    assert await metadata.get_value("r-1", "deletionProtection") is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={}),
        httpx.Response(403, json={}),
        httpx.Response(200, json={"metadata": [{"key": "deletionProtection", "value": "@@@"}]}),
    ],
)
async def test_a_failed_or_malformed_read_is_a_provider_error(
    key_file: Path, response: httpx.Response
) -> None:
    metadata = driver(key_file, "users", lambda _r: response)
    with pytest.raises(ProviderError):
        await metadata.get_value("r-1", "deletionProtection")
