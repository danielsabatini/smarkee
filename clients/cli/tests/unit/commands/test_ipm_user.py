"""Comandos `sk ipm user`: pedidos, espera, mensagens e saídas, contra uma API simulada."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from sk.identity.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.main import app

runner = CliRunner()
API = "https://api.teste"
ORG = "01a14168-b59d-7475-8db7-c5cf57fa100b"
UID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
PATH = "/v1/ipm/users"
USER = f"{PATH}/{UID}"
OPERATION = f"{USER}/operations/{OPID}"


class Response:
    def __init__(self, status: int, document: object) -> None:
        self.status = status
        self._body = json.dumps(document).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeApi:
    """Substitui `urlopen`: responde por (método, caminho) e grava os pedidos recebidos."""

    def __init__(self) -> None:
        self.routes: dict[
            tuple[str, str],
            Response | urllib.error.HTTPError | list[Response | urllib.error.HTTPError],
        ] = {}
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Response:
        self.requests.append(request)
        key = (request.get_method(), request.full_url.removeprefix(API).split("?")[0])
        found = self.routes.get(key)
        if found is None:
            raise AssertionError(f"rota não prevista: {key}")
        if isinstance(found, list):
            found = found.pop(0) if len(found) > 1 else found[0]
        if isinstance(found, urllib.error.HTTPError):
            raise found
        return found


def http_error(
    status: int, error_code: str, message: str, field: str | None = None
) -> urllib.error.HTTPError:
    document = {"errorCode": error_code, "message": message, **({"field": field} if field else {})}
    body = io.BytesIO(json.dumps(document).encode())
    return urllib.error.HTTPError(API, status, message, hdrs=None, fp=body)  # type: ignore[arg-type]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeApi]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("SK_API_URL", raising=False)
    monkeypatch.delenv("SK_IPM_ORGANIZATION_ID", raising=False)
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(
        f'[api]\nurl = "{API}"\n\n[ipm]\norganizationId = "{ORG}"\n', encoding="utf-8"
    )
    fake = FakeApi()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    save_credentials(
        default_credentials_path(),
        StoredCredentials(
            issuer="https://ipm.teste",
            client_id="cli",
            token_type="Bearer",
            access_token="access-1",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token="refresh-1",
            id_token=None,
            scope="openid",
            obtained_at=datetime.now(UTC),
        ),
    )
    yield fake


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("sk.commands.ipm_user.time.sleep", no_wait)


def user_document(
    *,
    phase: str = "Ready",
    roles: list[str] | None = None,
    protected: bool = False,
    version: str = "3",
    state: str | None = "initial",
) -> dict[str, Any]:
    roles = roles if roles is not None else ["ipm.user.get"]
    return {
        "resourceId": UID,
        "resourceVersion": version,
        "desiredGeneration": 1,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "organizationId": ORG,
            "roles": roles,
            "deletionProtection": protected,
            "givenName": "Bia",
            "familyName": "Lima",
            "email": "bia@example.com",
        },
        **(
            {
                "observed": {
                    "presence": "present",
                    "observedAt": "2026-10-21T10:00:00+00:00",
                    "userState": state,
                    "roles": roles,
                }
            }
            if state
            else {}
        ),
        "createdAt": "2026-10-21T10:00:00+00:00",
        "updatedAt": "2026-10-21T10:00:05+00:00",
    }


def operation_document(status: str, reason: str | None = None) -> Response:
    document: dict[str, Any] = {"operationId": OPID, "operationStatus": status}
    if reason:
        document["operationStatusReason"] = reason
    return Response(200, document)


def accepted() -> Response:
    return Response(202, {"resourceId": UID, "operationId": OPID})


def body_of(request: urllib.request.Request) -> Any:
    return json.loads(cast(bytes, request.data))


def create(*extra: str) -> list[str]:
    return [
        "ipm", "user", "create", "--name", "Bia", "--surname", "Lima",
        "--email", "bia@example.com", *extra,
    ]  # fmt: skip


def test_create_uses_the_active_organization_and_sends_sorted_roles(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()

    result = runner.invoke(app, create("--role", "ipm.user.list", "--role", "ipm.user.get"))

    assert result.exit_code == 0, result.stdout + result.stderr
    request = api.requests[-1]
    assert request.get_header("Authorization") == "Bearer access-1"
    assert request.get_header("Idempotency-key")
    assert body_of(request) == {
        "organizationId": ORG,
        "givenName": "Bia",
        "familyName": "Lima",
        "email": "bia@example.com",
        "roles": ["ipm.user.get", "ipm.user.list"],
    }
    assert "password" not in json.dumps(body_of(request))
    assert f"sk ipm user get --resource-id {UID}" in " ".join(result.stdout.split())


def test_create_takes_the_organization_option_over_the_active_one(api: FakeApi) -> None:
    other = "01a15e61-1eca-71b3-96b9-4068290bd618"
    api.routes[("POST", PATH)] = accepted()
    result = runner.invoke(app, create("--organization-id", other))
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1])["organizationId"] == other


def test_create_validates_before_any_call(api: FakeApi) -> None:
    for arguments in (
        ["ipm", "user", "create", "--surname", "Lima", "--email", "bia@example.com"],
        create("--role", "Nao Valida"),
        ["ipm", "user", "create", "--name", "Bia", "--surname", "Lima", "--email", "nao-email"],
        create("--organization-id", "Org Inválida"),
    ):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 2, arguments
    assert api.requests == []


def test_create_wait_waits_for_ready_and_shows_the_user(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation_document("in_progress"),
        operation_document("completed"),
    ]
    api.routes[("GET", USER)] = [
        Response(200, user_document(phase="Pending", state=None)),
        Response(200, user_document()),
    ]
    result = runner.invoke(app, create("--role", "ipm.user.get", "--wait"))
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "User created" in result.stdout and "initial" in result.stdout


def test_a_rejected_creation_explains_why(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("rejected", "validation")
    api.routes[("GET", USER)] = http_error(404, "NotFound", "Recurso não encontrado.")
    result = runner.invoke(app, create("--wait"))
    assert result.exit_code == 1
    assert "already in use in the Organization" in " ".join(result.stderr.split())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (http_error(403, "Forbidden", "x"), "Without ipm.user.bind"),
        (http_error(403, "QuotaExceeded", "x"), "user limit"),
        (http_error(400, "ValidationFailed", "Roles não liberadas", field="roles"), "grant"),
        (http_error(404, "NotFound", "x"), "do not act on it"),
    ],
)
def test_api_refusals_have_english_hints(
    api: FakeApi, error: urllib.error.HTTPError, expected: str
) -> None:
    api.routes[("POST", PATH)] = error
    result = runner.invoke(app, create("--role", "ipm.user.bind"))
    assert result.exit_code in (1, 2)
    assert expected in " ".join(result.stderr.split())
    assert "liberadas" not in result.stderr  # a mensagem do servidor (pt-BR) não aparece


def test_update_replaces_the_roles_reading_the_current_version(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(version="7"))
    api.routes[("PATCH", USER)] = accepted()
    result = runner.invoke(
        app, ["ipm", "user", "update", "--resource-id", UID, "--role", "ipm.user.list"]
    )
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {"resourceVersion": "7", "roles": ["ipm.user.list"]}


def test_update_needs_roles_or_no_roles_and_is_idempotent(api: FakeApi) -> None:
    neither = runner.invoke(app, ["ipm", "user", "update", "--resource-id", UID])
    both = runner.invoke(
        app, ["ipm", "user", "update", "--resource-id", UID, "--role", "a.b.c", "--no-roles"]
    )
    assert (neither.exit_code, both.exit_code) == (2, 2)
    assert api.requests == []
    api.routes[("GET", USER)] = Response(200, user_document(roles=[]))
    same = runner.invoke(app, ["ipm", "user", "update", "--resource-id", UID, "--no-roles"])
    assert same.exit_code == 0 and "Nothing to do" in same.stdout
    assert [r.get_method() for r in api.requests] == ["GET"]


def test_protect_and_unprotect_change_only_the_protection(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(protected=False))
    api.routes[("PATCH", USER)] = accepted()
    result = runner.invoke(app, ["ipm", "user", "protect", "--resource-id", UID])
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {"resourceVersion": "3", "deletionProtection": True}
    again = runner.invoke(app, ["ipm", "user", "unprotect", "--resource-id", UID])
    assert again.exit_code == 0 and "Nothing to do" in again.stdout


def test_delete_reads_the_version_and_explains_the_protection(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(version="4"))
    api.routes[("DELETE", USER)] = accepted()
    result = runner.invoke(app, ["ipm", "user", "delete", "--resource-id", UID])
    assert result.exit_code == 0, result.stderr
    assert "resourceVersion=4" in api.requests[-1].full_url
    api.routes[("DELETE", USER)] = http_error(409, "DeletionProtected", "x")
    refused = runner.invoke(app, ["ipm", "user", "delete", "--resource-id", UID])
    assert refused.exit_code == 1 and "sk ipm user unprotect" in refused.stderr


def test_get_and_list_show_the_users(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    shown = runner.invoke(app, ["ipm", "user", "get", "--resource-id", UID])
    assert shown.exit_code == 0 and "bia@example.com" in shown.stdout
    api.routes[("GET", PATH)] = Response(200, {"items": [user_document()]})
    listed = runner.invoke(app, ["ipm", "user", "list"])
    assert listed.exit_code == 0 and UID in listed.stdout
    assert f"organizationId={ORG}" in api.requests[-1].full_url


def test_without_an_active_organization_the_option_is_required(
    api: FakeApi, tmp_path: Path
) -> None:
    (tmp_path / "sk" / "config.toml").write_text(f'[api]\nurl = "{API}"\n', encoding="utf-8")
    result = runner.invoke(app, ["ipm", "user", "list"])
    assert result.exit_code == 2 and "--organization-id" in result.stderr
    assert api.requests == []
