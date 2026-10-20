"""Cliente de escrita do provedor de identidade: operações idempotentes e erros."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ipm_organization.executor.domain.identity import IdentityOrganization, ProviderError
from ipm_organization.executor.provider.identity import IdentityWriter
from ipm_organization.executor.settings import IdentitySettings

NOT_FOUND = {"code": 5, "message": "x (QUERY-Dfbg2)", "details": [{"id": "QUERY-Dfbg2"}]}


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
        base_url="http://z",
    )
    return IdentityWriter(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


async def test_create_organization_uses_the_resource_id_as_the_organization_id(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    z = writer(key_file, lambda r: httpx.Response(201, json={"organizationId": "o-1"}), calls)

    created = await z.create_organization("o-1", name="acme")

    assert created is True
    assert (calls[0].method, calls[0].url.path) == ("POST", "/v2/organizations")
    assert json.loads(calls[0].content) == {"name": "acme", "organizationId": "o-1"}
    assert calls[0].headers["authorization"] == "Bearer tok"
    assert calls[0].headers["host"] == "localhost:8080"


async def test_create_organization_that_already_exists_is_reported_not_raised(
    key_file: Path,
) -> None:
    conflict = httpx.Response(409, json={"code": 6, "details": [{"id": "ORG-laho2n"}]})
    assert await writer(key_file, lambda r: conflict).create_organization("o-1", name="a") is False


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
        (409, "Rejected", False),  # conflito só é esperado na criação
    ],
)
async def test_errors_are_classified(
    key_file: Path, status: int, reason: str, retryable: bool
) -> None:
    z = writer(key_file, lambda r: httpx.Response(status, json={"code": 3, "details": []}))
    with pytest.raises(ProviderError) as raised:
        await z.deactivate_organization("o-1")
    assert (raised.value.reason, raised.value.retryable) == (reason, retryable)


async def test_network_errors_are_retryable(key_file: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(ProviderError) as raised:
        await writer(key_file, boom).delete_organization("o-1")
    assert (raised.value.reason, raised.value.retryable) == ("ProviderUnavailable", True)


async def test_error_text_never_carries_the_identity_provider_message(key_file: Path) -> None:
    secret = "nome-do-pedido"
    z = writer(
        key_file,
        lambda r: httpx.Response(
            400, json={"code": 3, "message": secret, "details": [{"id": "X-1", "message": secret}]}
        ),
    )
    with pytest.raises(ProviderError) as raised:
        await z.create_organization("o-1", name=secret)
    assert secret not in str(raised.value)


async def test_delete_organization_missing_is_success_but_ambiguous_404_is_an_error(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    z = writer(key_file, lambda r: httpx.Response(404, json=NOT_FOUND), calls)
    await z.delete_organization("o-1")
    assert (calls[0].method, calls[0].url.path) == ("DELETE", "/v2/organizations/o-1")
    with pytest.raises(ProviderError):
        await writer(key_file, lambda r: httpx.Response(404, text="nginx")).delete_organization("o")


async def test_get_organization_reads_name_and_state_by_exact_id(key_file: Path) -> None:
    calls: list[httpx.Request] = []
    body = {"result": [{"id": "o-1", "name": "acme", "state": "ORGANIZATION_STATE_INACTIVE"}]}
    z = writer(key_file, lambda r: httpx.Response(200, json=body), calls)

    organization = await z.get_organization("o-1")

    assert organization == IdentityOrganization("acme", active=False)
    assert calls[0].url.path == "/zitadel.org.v2.OrganizationService/ListOrganizations"
    assert json.loads(calls[0].content) == {"queries": [{"idQuery": {"id": "o-1"}}]}


async def test_get_organization_without_result_or_with_another_id_is_none(key_file: Path) -> None:
    empty = writer(key_file, lambda r: httpx.Response(200, json={"details": {}}))
    assert await empty.get_organization("o-1") is None
    other = {"result": [{"id": "o-2", "name": "x", "state": "ORGANIZATION_STATE_ACTIVE"}]}
    assert (
        await writer(key_file, lambda r: httpx.Response(200, json=other)).get_organization("o-1")
        is None
    )


async def test_rename_activate_and_deactivate_use_the_v2_organization_routes(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    z = writer(key_file, lambda r: httpx.Response(200, json={}), calls)

    await z.rename_organization("o-1", name="novo")
    await z.activate_organization("o-1")
    await z.deactivate_organization("o-1")

    assert [(c.method, c.url.path) for c in calls] == [
        ("POST", "/v2/organizations/o-1"),
        ("POST", "/v2/organizations/o-1/activate"),
        ("POST", "/v2/organizations/o-1/deactivate"),
    ]
    assert json.loads(calls[0].content) == {"name": "novo"}


@pytest.mark.parametrize(
    ("call", "error_id"),
    [
        ("rename", "ORG-4VSdf"),
        ("activate", "EVENT-bfnrh"),
        ("deactivate", "EVENT-Dbs2g"),
    ],
)
async def test_an_already_reached_state_counts_as_success(
    key_file: Path, call: str, error_id: str
) -> None:
    z = writer(
        key_file, lambda r: httpx.Response(400, json={"code": 9, "details": [{"id": error_id}]})
    )
    match call:
        case "rename":
            await z.rename_organization("o-1", name="acme")
        case "activate":
            await z.activate_organization("o-1")
        case _:
            await z.deactivate_organization("o-1")


async def test_another_precondition_failure_is_still_an_error(key_file: Path) -> None:
    z = writer(
        key_file, lambda r: httpx.Response(400, json={"code": 9, "details": [{"id": "X-1"}]})
    )
    with pytest.raises(ProviderError):
        await z.deactivate_organization("o-1")
