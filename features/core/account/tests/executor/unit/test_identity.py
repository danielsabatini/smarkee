"""Cliente de escrita do provedor de identidade: operações idempotentes e erros."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core_account.executor.domain.identity import ProviderError
from core_account.executor.provider.identity import IdentityWriter
from core_account.executor.settings import IdentitySettings

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


def writer(
    key_file: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    calls: list[httpx.Request] | None = None,
) -> IdentityWriter:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if calls is not None:
            calls.append(request)
        return handler(request)

    settings = IdentitySettings(
        key_file=str(key_file),
        register_organization_id="org-r",
        project_ids={"core": "proj-core", "sum": "proj-sum"},
        base_url="http://z",
    )
    return IdentityWriter(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


async def test_create_user_has_no_password_and_uses_the_resource_id(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    z = writer(key_file, lambda r: httpx.Response(201, json={"userId": "u-1"}), calls)

    created = await z.create_user("u-1", given_name="Ana", family_name="Souza", email="a@x.com")

    assert created is True
    body = json.loads(calls[0].content)
    assert (calls[0].method, calls[0].url.path) == ("POST", "/v2/users/human")
    assert body["userId"] == "u-1" and body["organization"] == {"orgId": "org-r"}
    assert body["username"] == "a@x.com" and "password" not in body
    assert calls[0].headers["authorization"] == "Bearer tok"
    assert calls[0].headers["host"] == "localhost:8080"


async def test_create_user_that_already_exists_is_reported_not_raised(key_file: Path) -> None:
    z = writer(key_file, lambda r: httpx.Response(400, json=ALREADY))
    assert await z.create_user("u-1", given_name="A", family_name="B", email="a@x.com") is False


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
        await z.delete_user("u-1")
    assert (raised.value.reason, raised.value.retryable) == (reason, retryable)


async def test_network_errors_are_retryable(key_file: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(ProviderError) as raised:
        await writer(key_file, boom).delete_user("u-1")
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
        await z.create_user("u-1", given_name="A", family_name="B", email=secret)
    assert secret not in str(raised.value)


async def test_delete_user_missing_is_success_but_ambiguous_404_is_an_error(key_file: Path) -> None:
    await writer(key_file, lambda r: httpx.Response(404, json=NOT_FOUND)).delete_user("u-1")
    with pytest.raises(ProviderError):
        await writer(key_file, lambda r: httpx.Response(404, text="nginx")).delete_user("u-1")


async def test_get_user_reads_the_email(key_file: Path) -> None:
    body = {"user": {"human": {"email": {"email": "a@x.com"}}}}
    user = await writer(key_file, lambda r: httpx.Response(200, json=body)).get_user("u-1")
    assert user is not None and user.email == "a@x.com"
    assert (
        await writer(key_file, lambda r: httpx.Response(404, json=NOT_FOUND)).get_user("u") is None
    )


async def test_grants_and_their_mutations_use_the_v2_authorization_service(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ListAuthorizations"):
            return httpx.Response(
                200,
                json={
                    "authorizations": [
                        {
                            "id": "g-1",
                            "project": {"id": "proj-core"},
                            "roles": [{"key": "core.account.get"}],
                        },
                        # Projeto fora de `project_ids`: o Executor não o enxerga.
                        {"id": "g-9", "project": {"id": "proj-outro"}, "roles": [{"key": "x.y.z"}]},
                    ]
                },
            )
        return httpx.Response(200, json={})

    z = writer(key_file, handler, calls)
    grants = await z.grants("u-1")
    assert [(g.grant_id, g.project_id, set(g.roles)) for g in grants] == [
        ("g-1", "proj-core", {"core.account.get"})
    ]
    await z.create_grant("u-1", "proj-core", ["a", "b"])
    await z.update_grant("g-1", ["a"])
    await z.remove_grant("g-1")

    service = "/zitadel.authorization.v2.AuthorizationService"
    assert [(c.method, c.url.path) for c in calls] == [
        ("POST", f"{service}/ListAuthorizations"),
        ("POST", f"{service}/CreateAuthorization"),
        ("POST", f"{service}/UpdateAuthorization"),
        ("POST", f"{service}/DeleteAuthorization"),
    ]
    assert all(c.headers["Connect-Protocol-Version"] == "1" for c in calls)
    assert all("x-zitadel-orgid" not in c.headers for c in calls)
    assert json.loads(calls[0].content)["filters"] == [
        {"inUserIds": {"ids": ["u-1"]}},
        {"organizationId": {"id": "org-r"}},
    ]
    # A organização vai no corpo; o teto de roles é o Project Grant, aplicado pelo Zitadel.
    assert json.loads(calls[1].content) == {
        "userId": "u-1",
        "projectId": "proj-core",
        "organizationId": "org-r",
        "roleKeys": ["a", "b"],
    }
    assert json.loads(calls[2].content) == {"id": "g-1", "roleKeys": ["a"]}
    assert json.loads(calls[3].content) == {"id": "g-1"}


async def test_the_project_of_a_role_comes_from_its_module(key_file: Path) -> None:
    z = writer(key_file, lambda r: httpx.Response(200, json={}))
    assert z.project_of("core.account.get") == "proj-core"
    assert z.project_of("sum.ipm.enable") == "proj-sum"
    # `ipm` não está em `project_ids`: o Executor da Account não concede roles dele (decisão 0032).
    with pytest.raises(ProviderError) as raised:
        z.project_of("ipm.organization.get")
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)


async def test_creating_an_existing_authorization_is_success_and_other_errors_are_not(
    key_file: Path,
) -> None:
    exists = {
        "code": "already_exists",
        "details": [{"debug": {"id": "V3-DKcYh"}, "id": "V3-DKcYh"}],
    }
    await writer(key_file, lambda r: httpx.Response(409, json=exists)).create_grant(
        "u-1", "proj-core", ["a"]
    )
    with pytest.raises(ProviderError):
        await writer(key_file, lambda r: httpx.Response(403, json={})).create_grant(
            "u-1", "proj-core", ["a"]
        )


async def test_removing_a_missing_authorization_is_success(key_file: Path) -> None:
    missing = {"code": "not_found", "message": "x", "details": [{"id": "COMMAND-3M9sd"}]}
    await writer(key_file, lambda r: httpx.Response(404, json=missing)).remove_grant("g-1")


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
    z = IdentityWriter(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))
    await z.delete_user("u-1")
    await z.delete_user("u-2")
    assert len(tokens) == 1

    broken = IdentityWriter(
        IdentitySettings(key_file=str(tmp_path / "x.json")),
        httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    with pytest.raises(ProviderError) as raised:
        await broken.delete_user("u-1")
    assert (raised.value.reason, raised.value.retryable) == ("Unauthorized", False)
