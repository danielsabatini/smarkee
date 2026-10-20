"""Driver de leitura da organização sobre a conexão do Observer: ausência só com consulta vazia."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ipm_organization.observer.domain.identity import ProviderError
from ipm_organization.observer.drivers.organization import OrganizationDriver
from ipm_organization.observer.provider.identity import IdentityConnection
from ipm_organization.observer.settings import IdentitySettings


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


def settings(key_file: Path) -> IdentitySettings:
    return IdentitySettings(
        key_file=str(key_file),
        base_url="http://z",
    )


def reader(
    key_file: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    calls: list[httpx.Request] | None = None,
) -> OrganizationDriver:
    def route(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return OrganizationDriver(IdentityConnection(settings(key_file), client))


async def test_it_authenticates_with_a_jwt_assertion_and_reuses_the_token(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    identity = reader(
        key_file,
        lambda r: httpx.Response(200, json={"result": []}),
        calls=calls,
    )
    await identity.get_organization("o-1")
    await identity.get_organization("o-2")

    token_calls = [c for c in calls if c.url.path == "/oauth/v2/token"]
    assert len(token_calls) == 1  # token em cache
    form = dict(item.split("=") for item in token_calls[0].content.decode().split("&"))
    claims = jwt.decode(form["assertion"], options={"verify_signature": False})
    assert (claims["iss"], claims["sub"]) == ("svc-1", "svc-1")
    assert claims["aud"] == "http://localhost:8080"
    assert jwt.get_unverified_header(form["assertion"])["kid"] == "key-1"
    api = [c for c in calls if c.url.path.startswith("/zitadel.org.v2.")]
    assert api[0].headers["authorization"] == "Bearer tok"
    assert api[0].headers["host"] == "localhost:8080"


def found(**fields: str) -> dict[str, object]:
    return {
        "result": [{"id": "o-1", "name": "acme", "state": "ORGANIZATION_STATE_ACTIVE", **fields}]
    }


async def test_get_organization_maps_the_fields_and_queries_by_exact_id(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    identity = reader(key_file, lambda r: httpx.Response(200, json=found()), calls=calls)

    organization = await identity.get_organization("o-1")

    assert organization is not None
    assert (organization.name, organization.state) == ("acme", "ORGANIZATION_STATE_ACTIVE")
    request = next(c for c in calls if "ListOrganizations" in c.url.path)
    assert request.url.path == "/zitadel.org.v2.OrganizationService/ListOrganizations"
    assert request.headers["Connect-Protocol-Version"] == "1"
    assert json.loads(request.content) == {"queries": [{"idQuery": {"id": "o-1"}}]}


async def test_an_empty_successful_query_means_the_organization_does_not_exist(
    key_file: Path,
) -> None:
    assert (
        await reader(key_file, lambda r: httpx.Response(200, json={})).get_organization("o-1")
        is None
    )
    empty = httpx.Response(200, json={"details": {}, "result": []})
    assert await reader(key_file, lambda r: empty).get_organization("o-1") is None


async def test_a_result_for_another_id_is_not_the_organization(key_file: Path) -> None:
    body = found(id="o-2")
    assert (
        await reader(key_file, lambda r: httpx.Response(200, json=body)).get_organization("o-1")
        is None
    )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={"code": 5, "message": "Not Found"}),  # caminho errado
        httpx.Response(404, text="<html>nginx</html>"),
        httpx.Response(401, json={"code": 16}),
        httpx.Response(403, json={"code": 7}),
        httpx.Response(429, json={"code": 8}),
        httpx.Response(500, json={"code": 13}),
        httpx.Response(200, text="não é json"),
    ],
)
async def test_every_failure_is_a_provider_error_never_absence(
    key_file: Path, response: httpx.Response
) -> None:
    with pytest.raises(ProviderError):
        await reader(key_file, lambda r: response).get_organization("o-1")


async def test_network_failures_are_provider_errors(key_file: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(ProviderError):
        await reader(key_file, boom).get_organization("o-1")


async def test_missing_key_file_or_token_failure_is_a_provider_error(tmp_path: Path) -> None:
    missing = OrganizationDriver(
        IdentityConnection(
            IdentitySettings(key_file=str(tmp_path / "nao-existe.json")),
            httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        )
    )
    with pytest.raises(ProviderError):
        await missing.get_organization("o-1")
