"""Driver de escrita do metadado: caminho por dono, valor em base64 e erros do provedor."""

import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core_account.executor.domain.identity import ProviderError
from core_account.executor.drivers.metadata import MetadataDriver, Owner
from core_account.executor.provider.identity import IdentityConnection
from core_account.executor.settings import IdentitySettings


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
    calls: list[httpx.Request],
) -> MetadataDriver:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        calls.append(request)
        return handler(request)

    settings = IdentitySettings(key_file=str(key_file), base_url="http://z")
    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return MetadataDriver(IdentityConnection(settings, client), owner)


@pytest.mark.parametrize("owner", ["organizations", "users"])
async def test_set_value_writes_only_the_key_in_base64_under_the_owner(
    key_file: Path, owner: Owner
) -> None:
    calls: list[httpx.Request] = []
    metadata = driver(key_file, owner, lambda _r: httpx.Response(200, json={"setDate": "x"}), calls)

    await metadata.set_value("r-1", "deletionProtection", "true")

    (request,) = calls
    assert (request.method, request.url.path) == ("POST", f"/v2/{owner}/r-1/metadata")
    body = json.loads(request.content)
    assert body == {
        "metadata": [{"key": "deletionProtection", "value": base64.b64encode(b"true").decode()}]
    }


async def test_a_refusal_of_the_provider_is_a_provider_error(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    metadata = driver(key_file, "users", lambda _r: httpx.Response(403, json={}), calls)
    with pytest.raises(ProviderError) as raised:
        await metadata.set_value("r-1", "deletionProtection", "false")
    assert (raised.value.reason, raised.value.retryable) == ("Unauthorized", False)
