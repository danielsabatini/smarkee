"""Cliente de escrita do provedor de identidade: operações idempotentes e erros."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ipm_user.executor.actions.user_actions import Drivers
from ipm_user.executor.domain.identity import ProviderError
from ipm_user.executor.drivers.authorization import AuthorizationDriver
from ipm_user.executor.drivers.metadata import MetadataDriver
from ipm_user.executor.drivers.user import UserDriver
from ipm_user.executor.provider.identity import IdentityConnection
from ipm_user.executor.settings import IdentitySettings

NOT_FOUND = {"code": 5, "message": "x (QUERY-Dfbg2)", "details": [{"id": "QUERY-Dfbg2"}]}
ALREADY = {"code": 9, "message": "x", "details": [{"id": "COMMAND-7yiox1isql"}]}


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


def drivers(settings: IdentitySettings, client: httpx.AsyncClient) -> Drivers:
    """Os drivers de escrita sobre uma conexão só, como no `main` do Executor."""
    connection = IdentityConnection(settings, client)
    return Drivers(
        users=UserDriver(connection),
        authorizations=AuthorizationDriver(connection, settings),
        metadata=MetadataDriver(connection, "users"),
    )


def writer(
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
        project_id="proj-ipm",
        base_url="http://z",
    )
    return drivers(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


async def test_create_user_has_no_password_and_uses_the_resource_id(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    z = writer(key_file, lambda r: httpx.Response(201, json={"userId": "u-1"}), calls)

    created = await z.users.create_user(
        "u-1", organization_id="org-c", given_name="Ana", family_name="Souza", email="a@x.com"
    )

    assert created is True
    body = json.loads(calls[0].content)
    assert (calls[0].method, calls[0].url.path) == ("POST", "/v2/users/human")
    assert body["userId"] == "u-1" and body["organization"] == {"orgId": "org-c"}
    assert body["username"] == "a@x.com" and "password" not in body
    assert calls[0].headers["authorization"] == "Bearer tok"
    assert calls[0].headers["host"] == "localhost:8080"


async def test_create_user_that_already_exists_is_reported_not_raised(key_file: Path) -> None:
    z = writer(key_file, lambda r: httpx.Response(400, json=ALREADY))
    assert (
        await z.users.create_user(
            "u-1", organization_id="org-c", given_name="A", family_name="B", email="a@x.com"
        )
        is False
    )


@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (401, "Unauthorized", False),
        (403, "Unauthorized", False),
        (429, "ProviderUnavailable", True),
        (500, "ProviderUnavailable", True),
        (503, "ProviderUnavailable", True),
        (400, "Rejected", False),
        (422, "Rejected", False),
    ],
)
async def test_errors_are_classified(
    key_file: Path, status: int, reason: str, retryable: bool
) -> None:
    z = writer(key_file, lambda r: httpx.Response(status, json={"code": 3, "details": []}))
    with pytest.raises(ProviderError) as raised:
        await z.users.delete_user("u-1")
    assert (raised.value.reason, raised.value.retryable) == (reason, retryable)


async def test_network_errors_are_retryable(key_file: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(ProviderError) as raised:
        await writer(key_file, boom).users.delete_user("u-1")
    assert (raised.value.reason, raised.value.retryable) == ("ProviderUnavailable", True)


async def test_error_text_never_carries_the_identity_provider_message(key_file: Path) -> None:
    secret = "ana@example.com"
    z = writer(
        key_file,
        lambda r: httpx.Response(
            400, json={"code": 3, "message": secret, "details": [{"id": "X-1", "message": secret}]}
        ),
    )
    with pytest.raises(ProviderError) as raised:
        await z.users.create_user(
            "u-1", organization_id="org-c", given_name="A", family_name="B", email=secret
        )
    assert secret not in str(raised.value)


async def test_delete_user_missing_is_success_but_ambiguous_404_is_an_error(key_file: Path) -> None:
    await writer(key_file, lambda r: httpx.Response(404, json=NOT_FOUND)).users.delete_user("u-1")
    with pytest.raises(ProviderError):
        await writer(key_file, lambda r: httpx.Response(404, text="nginx")).users.delete_user("u-1")


async def test_get_user_reads_the_email_and_the_organization(key_file: Path) -> None:
    body = {
        "user": {"details": {"resourceOwner": "org-c"}, "human": {"email": {"email": "a@x.com"}}}
    }
    user = await writer(key_file, lambda r: httpx.Response(200, json=body)).users.get_user("u-1")
    assert user is not None and (user.email, user.organization_id) == ("a@x.com", "org-c")
    assert (
        await writer(key_file, lambda r: httpx.Response(404, json=NOT_FOUND)).users.get_user("u")
        is None
    )


async def test_the_authorization_and_its_mutations_use_the_v2_authorization_service(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ListAuthorizations"):
            return httpx.Response(
                200,
                json={
                    "authorizations": [
                        # Outro projeto: o Executor do User só enxerga `roles-ipm`.
                        {"id": "g-9", "project": {"id": "proj-outro"}, "roles": [{"key": "x.y.z"}]},
                        {
                            "id": "g-1",
                            "project": {"id": "proj-ipm"},
                            "roles": [{"key": "ipm.user.get"}],
                        },
                    ]
                },
            )
        return httpx.Response(200, json={})

    z = writer(key_file, handler, calls)
    authorization = await z.authorizations.authorization("u-1", "org-c")
    assert authorization is not None
    assert (authorization.authorization_id, set(authorization.permissions)) == (
        "g-1",
        {"ipm.user.get"},
    )
    await z.authorizations.create("u-1", "org-c", ["a", "b"])
    await z.authorizations.update("g-1", ["a"])
    await z.authorizations.remove("g-1")

    service = "/zitadel.authorization.v2.AuthorizationService"
    assert [(c.method, c.url.path) for c in calls] == [
        ("POST", f"{service}/ListAuthorizations"),
        ("POST", f"{service}/CreateAuthorization"),
        ("POST", f"{service}/UpdateAuthorization"),
        ("POST", f"{service}/DeleteAuthorization"),
    ]
    assert all(c.headers["Connect-Protocol-Version"] == "1" for c in calls)
    assert json.loads(calls[0].content)["filters"] == [
        {"inUserIds": {"ids": ["u-1"]}},
        {"organizationId": {"id": "org-c"}},
    ]
    # Na organização do usuário, sobre o Project Grant dela: o Grant é o teto (decisão 0077).
    assert json.loads(calls[1].content) == {
        "userId": "u-1",
        "projectId": "proj-ipm",
        "organizationId": "org-c",
        "roleKeys": ["a", "b"],
    }
    assert json.loads(calls[2].content) == {"id": "g-1", "roleKeys": ["a"]}
    assert json.loads(calls[3].content) == {"id": "g-1"}


async def test_without_an_authorization_in_roles_ipm_there_is_none(key_file: Path) -> None:
    empty = writer(key_file, lambda r: httpx.Response(200, json={"authorizations": []}))
    assert await empty.authorizations.authorization("u-1", "org-c") is None


async def test_creating_an_existing_authorization_is_success_and_other_errors_are_not(
    key_file: Path,
) -> None:
    exists = {
        "code": "already_exists",
        "details": [{"debug": {"id": "V3-DKcYh"}, "id": "V3-DKcYh"}],
    }
    await writer(key_file, lambda r: httpx.Response(409, json=exists)).authorizations.create(
        "u-1", "org-c", ["a"]
    )
    with pytest.raises(ProviderError):
        await writer(key_file, lambda r: httpx.Response(403, json={})).authorizations.create(
            "u-1", "org-c", ["a"]
        )


async def test_removing_a_missing_authorization_is_success(key_file: Path) -> None:
    missing = {"code": "not_found", "message": "x", "details": [{"id": "COMMAND-3M9sd"}]}
    await writer(key_file, lambda r: httpx.Response(404, json=missing)).authorizations.remove("g-1")


async def test_token_is_cached_and_a_missing_key_is_unauthorized(
    key_file: Path, tmp_path: Path
) -> None:
    tokens: list[int] = []

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            tokens.append(1)
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={})

    settings = IdentitySettings(key_file=str(key_file), base_url="http://z")
    z = drivers(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))
    await z.users.delete_user("u-1")
    await z.users.delete_user("u-2")
    assert len(tokens) == 1

    broken = drivers(
        IdentitySettings(key_file=str(tmp_path / "x.json")),
        httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    with pytest.raises(ProviderError) as raised:
        await broken.users.delete_user("u-1")
    assert (raised.value.reason, raised.value.retryable) == ("Unauthorized", False)
