"""Leitor do Zitadel do Observer: ausência só com 404 inequívoco; o resto é falha de leitura."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sum_service.observer.domain.authorization import Authorization, ProviderError
from sum_service.observer.domain.observation import Drivers
from sum_service.observer.drivers.authorization import AuthorizationDriver
from sum_service.observer.drivers.user import UserDriver
from sum_service.observer.provider.identity import IdentityConnection
from sum_service.observer.settings import IdentitySettings

USER_NOT_FOUND = {"code": 5, "message": "não encontrado", "details": [{"id": "QUERY-Dfbg2"}]}


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"userId": "svc-1", "keyId": "key-1", "key": pem}))
    return path


def reader(
    key_file: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    calls: list[httpx.Request] | None = None,
) -> Drivers:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if calls is not None:
            calls.append(request)
        return handler(request)

    settings = IdentitySettings(
        key_file=str(key_file),
        base_url="http://z",
        register_organization_id="org-r",
        project_ids={"ipm": "proj-ipm"},
    )
    connection = IdentityConnection(
        settings, httpx.AsyncClient(transport=httpx.MockTransport(route))
    )
    return Drivers(
        users=UserDriver(connection), authorizations=AuthorizationDriver(connection, settings)
    )


async def test_an_existing_user_exists_and_the_request_carries_the_token_and_the_host(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    identity = reader(key_file, lambda _r: httpx.Response(200, json={"user": {}}), calls)
    assert await identity.users.user_exists("u-1") is True
    assert calls[0].url.path == "/v2/users/u-1"
    assert calls[0].headers["authorization"] == "Bearer tok"
    assert calls[0].headers["host"] == "localhost:8080"


async def test_only_an_unambiguous_404_means_the_user_is_absent(key_file: Path) -> None:
    identity = reader(key_file, lambda _r: httpx.Response(404, json=USER_NOT_FOUND))
    assert await identity.users.user_exists("u-1") is False


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, text="proxy sem rota"),  # 404 sem o detalhe do Zitadel
        httpx.Response(404, json={"code": 5}),  # sem `details`
        httpx.Response(401),
        httpx.Response(403),
        httpx.Response(429),
        httpx.Response(503),
    ],
)
async def test_any_other_failure_is_a_read_error_never_an_absence(
    key_file: Path, response: httpx.Response
) -> None:
    identity = reader(key_file, lambda _r: response)
    with pytest.raises(ProviderError):
        await identity.users.user_exists("u-1")


async def test_a_network_error_is_a_read_error(key_file: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rede", request=request)

    with pytest.raises(ProviderError, match="ConnectError"):
        await reader(key_file, refuse).users.user_exists("u-1")


async def test_authorizations_keep_only_the_configured_projects_with_their_roles(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    body = {
        "authorizations": [
            {"project": {"id": "proj-ipm"}, "roles": [{"key": "ipm.organization.get"}]},
            {"project": {"id": "proj-outro"}, "roles": [{"key": "x.y.z"}]},
            {"project": {"id": "proj-ipm"}},  # sem roles
        ]
    }
    found = await reader(
        key_file, lambda _r: httpx.Response(200, json=body), calls
    ).authorizations.authorizations("u-1")
    assert found == [
        Authorization("proj-ipm", frozenset({"ipm.organization.get"})),
        Authorization("proj-ipm", frozenset()),
    ]
    sent = json.loads(calls[0].content)
    assert {"inUserIds": {"ids": ["u-1"]}} in sent["filters"]
    assert {"organizationId": {"id": "org-r"}} in sent["filters"]


@pytest.mark.parametrize(
    "response", [httpx.Response(200, text="não é json"), httpx.Response(200, json=[1])]
)
async def test_a_malformed_authorization_response_is_a_read_error(
    key_file: Path, response: httpx.Response
) -> None:
    with pytest.raises(ProviderError):
        await reader(key_file, lambda _r: response).authorizations.authorizations("u-1")


async def test_a_token_failure_is_a_read_error(tmp_path: Path) -> None:
    identity = reader(tmp_path / "nao-existe.json", lambda _r: httpx.Response(200, json={}))
    with pytest.raises(ProviderError, match="key unavailable"):
        await identity.users.user_exists("u-1")
