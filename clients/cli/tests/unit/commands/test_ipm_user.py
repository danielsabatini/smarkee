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

from sk import output
from sk.identity.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.main import app

runner = CliRunner()
API = "https://api.teste"
ORG = "01a14168-b59d-7475-8db7-c5cf57fa100b"
UID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
PATH = "/v1/ipm/users"
USER = f"{PATH}/{UID}"


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

    monkeypatch.setattr("sk.commands.shared.time.sleep", no_wait)


def user_document(
    *,
    phase: str = "Ready",
    permissions: list[str] | None = None,
    protected: bool = False,
    version: str = "3",
    state: str | None = "initial",
    desired_generation: int = 1,
    observed_generation: int | None = 1,
    conditions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    permissions = permissions if permissions is not None else ["ipm.user.get"]
    return {
        "resourceId": UID,
        "resourceVersion": version,
        "desiredGeneration": desired_generation,
        **({"observedGeneration": observed_generation} if observed_generation is not None else {}),
        "phase": phase,
        "conditions": conditions or [],
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "organizationId": ORG,
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
                    "permissions": permissions,
                    "effectivePermissions": permissions,
                }
            }
            if state
            else {}
        ),
        "createdAt": "2026-10-21T10:00:00+00:00",
        "updatedAt": "2026-10-21T10:00:05+00:00",
    }


def body_of(request: urllib.request.Request) -> Any:
    return json.loads(cast(bytes, request.data))


def create(*extra: str) -> list[str]:
    return [
        "ipm", "user", "create", "--name", "Bia", "--surname", "Lima",
        "--email", "bia@example.com", *extra,
    ]  # fmt: skip


def test_create_uses_the_active_organization_and_sends_sorted_roles(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = Response(
        201, user_document(phase="Pending", observed_generation=None)
    )

    result = runner.invoke(
        app, create("--role", "ipm.userViewer", "--role", "ipm.userAdmin", "--no-wait")
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    request = api.requests[-1]
    assert request.get_header("Authorization") == "Bearer access-1"
    assert request.get_header("Idempotency-key")
    assert body_of(request) == {
        "organizationId": ORG,
        "givenName": "Bia",
        "familyName": "Lima",
        "email": "bia@example.com",
        "roles": ["ipm.userAdmin", "ipm.userViewer"],
    }
    assert "password" not in json.dumps(body_of(request))
    assert f"sk ipm user get --resource-id {UID}" in " ".join(result.stdout.split())


def test_create_takes_the_organization_option_over_the_active_one(api: FakeApi) -> None:
    other = "01a15e61-1eca-71b3-96b9-4068290bd618"
    api.routes[("POST", PATH)] = Response(
        201, user_document(phase="Pending", observed_generation=None)
    )
    result = runner.invoke(app, create("--organization-id", other, "--no-wait"))
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
    api.routes[("POST", PATH)] = Response(
        201, user_document(phase="Pending", observed_generation=None)
    )
    api.routes[("GET", USER)] = [
        Response(200, user_document(phase="Pending", state=None, observed_generation=None)),
        Response(200, user_document(phase="Reconciling", state=None, observed_generation=None)),
        Response(200, user_document(phase="Ready", observed_generation=1)),
    ]
    result = runner.invoke(app, create("--role", "ipm.userViewer", "--wait"))
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "User created" in result.stdout and "initial" in result.stdout
    assert [r.get_method() for r in api.requests].count("GET") == 3


def test_name_in_use_is_explained(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = http_error(409, "NameInUse", "e-mail em uso", "email")
    result = runner.invoke(app, create())
    assert result.exit_code == 1
    assert "already exists in the Organization" in " ".join(result.stderr.split())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (http_error(403, "Forbidden", "x"), "requires ipm.user.bind"),
        (http_error(403, "QuotaExceeded", "x"), "user limit"),
        (
            http_error(400, "ValidationFailed", "Roles não liberadas", field="roles"),
            "roles in its catalog",
        ),
        (http_error(404, "NotFound", "x"), "do not act on it"),
    ],
)
def test_api_refusals_have_english_hints(
    api: FakeApi, error: urllib.error.HTTPError, expected: str
) -> None:
    api.routes[("POST", PATH)] = error
    result = runner.invoke(app, create("--role", "ipm.userViewer"))
    assert result.exit_code in (1, 2)
    assert expected in " ".join(result.stderr.split())
    assert "liberadas" not in result.stderr  # a mensagem do servidor (pt-BR) não aparece


def test_update_replaces_the_roles_reading_the_current_version(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(version="7"))
    api.routes[("PATCH", USER)] = Response(
        200, user_document(phase="Reconciling", desired_generation=2, version="8")
    )
    result = runner.invoke(
        app,
        [
            "ipm",
            "user",
            "update",
            "--resource-id",
            UID,
            "--role",
            "ipm.userViewer",
            "--group",
            "devops",
            "--no-wait",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {
        "resourceVersion": "7",
        "roles": ["ipm.userViewer"],
        "groups": ["devops"],
    }


def test_update_needs_roles_or_no_roles_and_is_idempotent(api: FakeApi) -> None:
    neither = runner.invoke(app, ["ipm", "user", "update", "--resource-id", UID])
    both = runner.invoke(
        app,
        [
            "ipm",
            "user",
            "update",
            "--resource-id",
            UID,
            "--role",
            "ipm.userViewer",
            "--no-roles",
        ],
    )
    assert (neither.exit_code, both.exit_code) == (2, 2)
    assert api.requests == []
    api.routes[("GET", USER)] = Response(200, user_document())
    same = runner.invoke(app, ["ipm", "user", "update", "--resource-id", UID, "--no-roles"])
    assert same.exit_code == 0 and "Nothing to do" in same.stdout
    assert [r.get_method() for r in api.requests] == ["GET"]


def test_update_waits_for_the_new_generation_not_a_stale_ready(api: FakeApi) -> None:
    api.routes[("GET", USER)] = [
        Response(200, user_document(protected=True)),  # leitura que escolhe a versão
        Response(200, user_document(phase="Ready", desired_generation=2, observed_generation=1)),
        Response(200, user_document(phase="Ready", desired_generation=2, observed_generation=2)),
    ]
    api.routes[("PATCH", USER)] = Response(
        200, user_document(phase="Reconciling", desired_generation=2, version="4")
    )
    result = runner.invoke(app, ["ipm", "user", "unprotect", "--resource-id", UID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert [r.get_method() for r in api.requests].count("GET") == 3


def test_a_failed_phase_with_the_generation_observed_is_a_failure(api: FakeApi) -> None:
    api.routes[("GET", USER)] = [
        Response(200, user_document(protected=True)),
        Response(
            200,
            user_document(
                phase="Failed",
                desired_generation=2,
                observed_generation=2,
                conditions=[
                    {
                        "type": "Ready",
                        "status": "False",
                        "reason": "ProviderRejected",
                        "lastTransitionAt": "2026-10-27T10:00:00Z",
                    }
                ],
            ),
        ),
    ]
    api.routes[("PATCH", USER)] = Response(
        200, user_document(phase="Reconciling", desired_generation=2, version="4")
    )
    result = runner.invoke(app, ["ipm", "user", "unprotect", "--resource-id", UID, "--wait"])
    assert result.exit_code == 1
    assert "ProviderRejected" in result.stderr


def test_protect_and_unprotect_change_only_the_protection(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(protected=False))
    api.routes[("PATCH", USER)] = Response(
        200, user_document(phase="Reconciling", desired_generation=2, version="4")
    )
    result = runner.invoke(app, ["ipm", "user", "protect", "--resource-id", UID, "--no-wait"])
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {"resourceVersion": "3", "deletionProtection": True}
    again = runner.invoke(app, ["ipm", "user", "unprotect", "--resource-id", UID])
    assert again.exit_code == 0 and "Nothing to do" in again.stdout


def test_delete_reads_the_version_and_explains_the_protection(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(version="4"))
    api.routes[("DELETE", USER)] = Response(202, user_document(phase="Deleting"))
    result = runner.invoke(app, ["ipm", "user", "delete", "--resource-id", UID, "--no-wait"])
    assert result.exit_code == 0, result.stderr
    assert "resourceVersion=4" in api.requests[-1].full_url
    api.routes[("DELETE", USER)] = http_error(409, "DeletionProtected", "x")
    refused = runner.invoke(app, ["ipm", "user", "delete", "--resource-id", UID])
    assert refused.exit_code == 1 and "sk ipm user unprotect" in refused.stderr


def test_delete_with_wait_finishes_when_the_resource_is_gone(api: FakeApi) -> None:
    api.routes[("GET", USER)] = [
        Response(200, user_document(protected=False)),
        Response(200, user_document(phase="Deleting", desired_generation=2, observed_generation=1)),
        http_error(404, "NotFound", "não encontrado"),
    ]
    api.routes[("DELETE", USER)] = Response(
        202, user_document(phase="Deleting", desired_generation=2)
    )
    result = runner.invoke(app, ["ipm", "user", "delete", "--resource-id", UID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert "removed" in result.stdout


def test_get_and_list_show_the_users(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    shown = runner.invoke(app, ["ipm", "user", "get", "--resource-id", UID])
    assert shown.exit_code == 0 and "bia@example.com" in shown.stdout
    api.routes[("GET", PATH)] = Response(200, {"items": [user_document()]})
    listed = runner.invoke(app, ["ipm", "user", "list"])
    assert listed.exit_code == 0 and UID in listed.stdout
    assert f"organizationId={ORG}" in api.requests[-1].full_url


def test_the_list_keeps_the_id_and_the_email_whole(api: FakeApi) -> None:
    """O `resourceId` e o e-mail não podem ser cortados (o usuário os copia)."""
    permissions = ["ipm.organization.get", "ipm.user.bind", "ipm.user.create", "ipm.user.get"]
    api.routes[("GET", PATH)] = Response(200, {"items": [user_document(permissions=permissions)]})
    listed = runner.invoke(app, ["ipm", "user", "list"])
    assert listed.exit_code == 0
    assert UID in listed.stdout and "bia@example.com" in listed.stdout
    assert "ipm.organization.get" not in listed.stdout  # as permissões ficam no `get`


def test_without_an_active_organization_the_option_is_required(
    api: FakeApi, tmp_path: Path
) -> None:
    (tmp_path / "sk" / "config.toml").write_text(f'[api]\nurl = "{API}"\n', encoding="utf-8")
    result = runner.invoke(app, ["ipm", "user", "list"])
    assert result.exit_code == 2 and "--organization-id" in result.stderr
    assert api.requests == []


# --- `--output json` (decisão 0093) -----------------------------------------------------------

JSON = ["--output", "json"]


@pytest.fixture
def default_output_mode() -> Iterator[None]:
    output.configure(raw=False)
    yield
    output.configure(raw=False)


def _document(stdout: str) -> Any:
    return json.loads(stdout)  # falha se houver mais de um documento ou texto solto


@pytest.mark.usefixtures("default_output_mode")
def test_json_get_and_list_print_native_types(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(protected=True))
    shown = runner.invoke(app, [*JSON, "ipm", "user", "get", "--resource-id", UID])
    assert shown.exit_code == 0, shown.stderr
    document = _document(shown.stdout)
    assert document["resourceId"] == UID and document["deletionProtection"] is True
    assert isinstance(document["permissions"], list) and isinstance(document["roles"], list)
    api.routes[("GET", PATH)] = Response(200, {"items": [user_document()]})
    listed = runner.invoke(app, [*JSON, "ipm", "user", "list"])
    assert [u["resourceId"] for u in _document(listed.stdout)] == [UID]
    api.routes[("GET", PATH)] = Response(200, {"items": []})
    assert _document(runner.invoke(app, [*JSON, "ipm", "user", "list"]).stdout) == []


@pytest.mark.usefixtures("default_output_mode")
def test_json_nothing_to_do_prints_the_current_user(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(protected=True))
    result = runner.invoke(app, [*JSON, "ipm", "user", "protect", "--resource-id", UID])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout)["resourceId"] == UID
    assert "Nothing to do" in result.stderr and "Nothing to do" not in result.stdout
    assert all(request.get_method() == "GET" for request in api.requests)


@pytest.mark.usefixtures("default_output_mode")
def test_json_delete_with_wait_prints_the_removed_state(api: FakeApi) -> None:
    api.routes[("GET", USER)] = [
        Response(200, user_document(protected=False)),  # leitura antes do pedido
        http_error(404, "NotFound", "gone"),  # já removido
    ]
    api.routes[("DELETE", USER)] = Response(202, user_document(phase="Deleting"))
    result = runner.invoke(app, [*JSON, "ipm", "user", "delete", "--resource-id", UID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout) == {"resourceId": UID, "state": "removed"}
