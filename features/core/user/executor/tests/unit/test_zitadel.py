"""Cliente de escrita do Zitadel: operações idempotentes e classificação dos erros."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core_user_executor.domain.identity import ProviderError
from core_user_executor.provider.zitadel import ZitadelWriter
from core_user_executor.settings import ZitadelSettings

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
) -> ZitadelWriter:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if calls is not None:
            calls.append(request)
        return handler(request)

    settings = ZitadelSettings(
        key_file=str(key_file), organization_id="org-1", project_id="proj-1", base_url="http://z"
    )
    return ZitadelWriter(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


async def test_create_user_has_no_password_and_uses_the_resource_id(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    z = writer(key_file, lambda r: httpx.Response(201, json={"userId": "u-1"}), calls)

    created = await z.create_user("u-1", given_name="Ana", family_name="Souza", email="a@x.com")

    assert created is True
    body = json.loads(calls[0].content)
    assert (calls[0].method, calls[0].url.path) == ("POST", "/v2/users/human")
    assert body["userId"] == "u-1" and body["organization"] == {"orgId": "org-1"}
    assert body["username"] == "a@x.com" and "password" not in body
    assert calls[0].headers["authorization"] == "Bearer tok"
    assert calls[0].headers["host"] == "ipm-dev.smarkee.com.br:8080"


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
        await z.send_password_link("u-1")
    assert (raised.value.reason, raised.value.retryable) == (reason, retryable)


async def test_network_errors_are_retryable(key_file: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(ProviderError) as raised:
        await writer(key_file, boom).delete_user("u-1")
    assert (raised.value.reason, raised.value.retryable) == ("ProviderUnavailable", True)


async def test_error_text_never_carries_the_zitadel_message(key_file: Path) -> None:
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


async def test_get_user_reads_email_and_password_state(key_file: Path) -> None:
    body = {"user": {"human": {"email": {"email": "a@x.com"}, "passwordChanged": "t"}}}
    user = await writer(key_file, lambda r: httpx.Response(200, json=body)).get_user("u-1")
    assert user is not None and (user.email, user.password_set) == ("a@x.com", True)
    assert (
        await writer(key_file, lambda r: httpx.Response(404, json=NOT_FOUND)).get_user("u") is None
    )


async def test_grants_and_their_mutations_use_the_organization_header(key_file: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/_search"):
            return httpx.Response(200, json={"result": [{"id": "g-1", "roleKeys": ["user.get"]}]})
        return httpx.Response(200, json={})

    z = writer(key_file, handler, calls)
    grants = await z.grants("u-1")
    assert [(g.grant_id, set(g.roles)) for g in grants] == [("g-1", {"user.get"})]
    await z.create_grant("u-1", ["a", "b"])
    await z.update_grant("u-1", "g-1", ["a"])
    await z.remove_grant("u-1", "g-1")

    assert all(c.headers["x-zitadel-orgid"] == "org-1" for c in calls)
    assert [(c.method, c.url.path) for c in calls[1:]] == [
        ("POST", "/management/v1/users/u-1/grants"),
        ("PUT", "/management/v1/users/u-1/grants/g-1"),
        ("DELETE", "/management/v1/users/u-1/grants/g-1"),
    ]
    assert json.loads(calls[1].content) == {"projectId": "proj-1", "roleKeys": ["a", "b"]}


async def test_token_is_cached_and_a_missing_key_is_unauthorized(
    key_file: Path, tmp_path: Path
) -> None:
    tokens: list[int] = []

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/v2/token":
            tokens.append(1)
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={})

    settings = ZitadelSettings(key_file=str(key_file), base_url="http://z")
    z = ZitadelWriter(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))
    await z.send_password_link("u-1")
    await z.send_password_link("u-2")
    assert len(tokens) == 1

    broken = ZitadelWriter(
        ZitadelSettings(key_file=str(tmp_path / "x.json")),
        httpx.AsyncClient(transport=httpx.MockTransport(route)),
    )
    with pytest.raises(ProviderError) as raised:
        await broken.send_password_link("u-1")
    assert (raised.value.reason, raised.value.retryable) == ("Unauthorized", False)
