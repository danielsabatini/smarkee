"""Cliente de leitura do provedor de identidade: ausência só com 404 inequívoco; o resto é falha."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ipm_serviceaccount.observer.domain.identity import ProviderError
from ipm_serviceaccount.observer.domain.observation import Drivers
from ipm_serviceaccount.observer.drivers.authorization import AuthorizationDriver
from ipm_serviceaccount.observer.drivers.metadata import MetadataDriver
from ipm_serviceaccount.observer.drivers.serviceaccount import ServiceAccountDriver
from ipm_serviceaccount.observer.provider.identity import IdentityConnection
from ipm_serviceaccount.observer.settings import IdentitySettings

USER_NOT_FOUND = {
    "code": 5,
    "message": "Usuário não pôde ser encontrado (QUERY-Dfbg2)",
    "details": [{"id": "QUERY-Dfbg2"}],
}


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
        project_id="proj-ipm",
        base_url="http://z",
    )


def drivers(identity: IdentitySettings, client: httpx.AsyncClient) -> Drivers:
    """Os drivers de leitura sobre uma conexão só, como no `main` do Observer."""
    connection = IdentityConnection(identity, client)
    return Drivers(
        machines=ServiceAccountDriver(connection),
        authorizations=AuthorizationDriver(connection, identity),
        metadata=MetadataDriver(connection, "users"),
    )


def reader(
    key_file: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    calls: list[httpx.Request] | None = None,
) -> Drivers:
    def route(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return drivers(settings(key_file), client)


async def test_it_authenticates_with_a_jwt_assertion_and_reuses_the_token(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    identity = reader(
        key_file,
        lambda r: httpx.Response(200, json={"user": {"state": "USER_STATE_ACTIVE"}}),
        calls=calls,
    )
    await identity.machines.get_machine("u-1")
    await identity.machines.get_machine("u-2")

    token_calls = [c for c in calls if c.url.path == "/oauth/v2/token"]
    assert len(token_calls) == 1  # token em cache
    form = dict(item.split("=") for item in token_calls[0].content.decode().split("&"))
    claims = jwt.decode(form["assertion"], options={"verify_signature": False})
    assert (claims["iss"], claims["sub"]) == ("svc-1", "svc-1")
    assert claims["aud"] == "http://localhost:8080"
    assert jwt.get_unverified_header(form["assertion"])["kid"] == "key-1"
    api = [c for c in calls if c.url.path.startswith("/v2/users/")]
    assert api[0].headers["authorization"] == "Bearer tok"
    assert api[0].headers["host"] == "localhost:8080"


async def test_get_machine_maps_the_state_and_the_token_type(key_file: Path) -> None:
    body = {
        "user": {
            "state": "USER_STATE_ACTIVE",
            "machine": {"accessTokenType": "ACCESS_TOKEN_TYPE_JWT"},
        }
    }
    z = reader(key_file, lambda r: httpx.Response(200, json=body))
    machine = await z.machines.get_machine("u-1")
    assert machine is not None
    assert (machine.state, machine.access_token_type) == (
        "USER_STATE_ACTIVE",
        "ACCESS_TOKEN_TYPE_JWT",
    )


async def test_list_keys_returns_only_ids_and_expirations_never_key_material(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    body = {
        "result": [
            {"id": "k1", "expirationDate": "2027-01-01T00:00:00Z", "publicKey": "NAO-LER"},
            {"id": "k2"},
        ]
    }
    identity = reader(key_file, lambda r: httpx.Response(200, json=body), calls=calls)

    keys = await identity.machines.list_keys("u-1")

    assert [(key.key_id, key.expires_at) for key in keys] == [
        ("k1", "2027-01-01T00:00:00Z"),
        ("k2", None),
    ]
    assert all(not hasattr(key, "public_key") for key in keys)
    request = next(c for c in calls if c.url.path.endswith("/ListKeys"))
    assert json.loads(request.content) == {"filters": [{"userIdFilter": {"id": "u-1"}}]}


async def test_an_unambiguous_404_means_the_user_does_not_exist(key_file: Path) -> None:
    identity = reader(key_file, lambda r: httpx.Response(404, json=USER_NOT_FOUND))
    assert await identity.machines.get_machine("u-1") is None


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
async def test_every_other_failure_is_a_provider_error_never_absence(
    key_file: Path, response: httpx.Response
) -> None:
    with pytest.raises(ProviderError):
        await reader(key_file, lambda r: response).machines.get_machine("u-1")


async def test_network_failures_are_provider_errors(key_file: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    with pytest.raises(ProviderError):
        await reader(key_file, boom).machines.get_machine("u-1")


async def test_missing_key_file_or_token_failure_is_a_provider_error(tmp_path: Path) -> None:
    missing = drivers(
        IdentitySettings(key_file=str(tmp_path / "nao-existe.json")),
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )
    with pytest.raises(ProviderError):
        await missing.machines.get_machine("u-1")


async def test_granted_permissions_are_those_of_roles_ipm_only(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    body = {
        "authorizations": [
            {
                "project": {"id": "proj-ipm"},
                "roles": [{"key": "ipm.serviceaccount.get"}, {"key": "ipm.serviceaccount.list"}],
            },
            # Outro projeto não conta: as permissões do usuário são as de `roles-ipm`.
            {"project": {"id": "proj-outro"}, "roles": [{"key": "x.y.z"}]},
        ]
    }
    identity = reader(key_file, lambda r: httpx.Response(200, json=body), calls=calls)

    assert await identity.authorizations.granted_permissions("u-1") == {
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
    }
    request = next(c for c in calls if "ListAuthorizations" in c.url.path)
    assert request.url.path == "/zitadel.authorization.v2.AuthorizationService/ListAuthorizations"
    assert request.headers["Connect-Protocol-Version"] == "1"
    assert json.loads(request.content)["filters"] == [{"inUserIds": {"ids": ["u-1"]}}]
