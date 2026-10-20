import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sum_service.executor.domain.identity import ProviderError
from sum_service.executor.drivers.authorization import AuthorizationDriver
from sum_service.executor.provider.identity import IdentityConnection
from sum_service.executor.settings import IdentitySettings


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"userId": "svc-1", "keyId": "key-1", "key": pem}))
    return path


def granter(
    key_file: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    calls: list[httpx.Request] | None = None,
) -> AuthorizationDriver:
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
    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return AuthorizationDriver(IdentityConnection(settings, client), settings)


async def test_grants_are_read_from_the_register_and_only_the_configured_projects(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    body = {
        "authorizations": [
            {
                "id": "g-1",
                "project": {"id": "proj-ipm"},
                "roles": [{"key": "ipm.organization.get"}],
            },
            {"id": "g-9", "project": {"id": "proj-outro"}, "roles": [{"key": "x.y.z"}]},
        ]
    }
    found = await granter(key_file, lambda _request: httpx.Response(200, json=body), calls).grants(
        "u-1"
    )
    assert [(g.grant_id, g.project_id) for g in found] == [("g-1", "proj-ipm")]
    filters = json.loads(calls[0].content)["filters"]
    assert {"organizationId": {"id": "org-r"}} in filters
    assert all(call.headers["Connect-Protocol-Version"] == "1" for call in calls)
    assert all("x-zitadel-orgid" not in call.headers for call in calls)


async def test_creating_an_existing_authorization_is_success(key_file: Path) -> None:
    exists = {"code": "already_exists", "details": [{"id": "V3-DKcYh"}]}
    await granter(key_file, lambda _request: httpx.Response(409, json=exists)).create_grant(
        "u-1", "proj-ipm", ["ipm.organization.get"]
    )


async def test_a_refusal_of_the_identity_provider_is_a_permanent_rejection(key_file: Path) -> None:
    with pytest.raises(ProviderError) as raised:
        await granter(key_file, lambda _request: httpx.Response(403, json={})).create_grant(
            "u-1", "proj-ipm", ["ipm.organization.get"]
        )
    assert (raised.value.reason, raised.value.retryable) == ("Unauthorized", False)


async def test_removing_a_missing_authorization_is_success(key_file: Path) -> None:
    missing = {"code": "not_found", "message": "x", "details": [{"id": "COMMAND-3M9sd"}]}
    await granter(key_file, lambda _request: httpx.Response(404, json=missing)).remove_grant("g-1")


async def test_a_module_without_a_project_is_refused_without_calling_the_identity_provider(
    key_file: Path,
) -> None:
    calls: list[httpx.Request] = []
    with pytest.raises(ProviderError):
        granter(key_file, lambda _request: httpx.Response(200, json={}), calls).project_of(
            "core.account.get"
        )
    assert calls == []
