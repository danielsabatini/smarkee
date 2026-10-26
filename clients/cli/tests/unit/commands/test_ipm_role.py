"""Comandos `sk ipm role`: pedidos, espera e saídas, contra uma API simulada."""

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
JSON = ["--output", "json"]
API = "https://api.teste"
RID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
PATH = "/v1/ipm/roles"
ROLE = f"{PATH}/{RID}"
OPERATION = f"{ROLE}/operations/{OPID}"


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
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(f'[api]\nurl = "{API}"\n', encoding="utf-8")
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


def role_document(
    *,
    phase: str = "Ready",
    name: str = "ipm.userAdmin",
    description: str = "Administrador de usuários",
    permissions: list[str] | None = None,
    protected: bool = False,
    version: str = "1",
) -> dict[str, Any]:
    permissions = permissions or ["ipm.user.get", "ipm.user.list"]
    return {
        "resourceId": RID,
        "resourceVersion": version,
        "desiredGeneration": 1,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "organizationId": "org-acme",
            "specification": {
                "name": name,
                "description": description,
                "permissions": permissions,
                "deletionProtection": protected,
                "status": "active",
            },
        },
        "createdAt": "2026-10-25T10:00:00+00:00",
        "updatedAt": "2026-10-25T10:00:05+00:00",
    }


def operation_document(status: str, reason: str | None = None) -> Response:
    document: dict[str, Any] = {"operationId": OPID, "operationStatus": status}
    if reason:
        document["operationStatusReason"] = reason
    return Response(200, document)


def accepted() -> Response:
    return Response(202, {"resourceId": RID, "operationId": OPID})


def body_of(request: urllib.request.Request) -> Any:
    return json.loads(cast(bytes, request.data))


def test_create_role(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    result = runner.invoke(
        app,
        [
            "ipm",
            "role",
            "create",
            "--organization-id",
            "org-acme",
            "--name",
            "bsm.accountAdmin",
            "--description",
            "Administrador de cobrança",
            "--permission",
            "bsm.account.get",
            "--permission",
            "bsm.account.create",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert body_of(api.requests[-1]) == {
        "organizationId": "org-acme",
        "name": "bsm.accountAdmin",
        "description": "Administrador de cobrança",
        "permissions": ["bsm.account.create", "bsm.account.get"],
    }


def test_update_role(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document(version="2"))
    api.routes[("PATCH", ROLE)] = accepted()
    result = runner.invoke(
        app,
        [
            "ipm",
            "role",
            "update",
            "--resource-id",
            RID,
            "--description",
            "Nova descrição da role",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {
        "resourceVersion": "2",
        "description": "Nova descrição da role",
    }


def test_protect_and_unprotect_role(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = [
        Response(200, role_document(protected=False)),
        Response(200, role_document(protected=True)),
    ]
    api.routes[("PATCH", ROLE)] = accepted()
    result = runner.invoke(app, ["ipm", "role", "protect", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {
        "resourceVersion": "1",
        "deletionProtection": True,
    }
    again = runner.invoke(app, ["ipm", "role", "protect", "--resource-id", RID])
    assert again.exit_code == 0 and "Nothing to do" in again.stdout


def test_delete_role(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document(version="3"))
    api.routes[("DELETE", ROLE)] = accepted()
    result = runner.invoke(app, ["ipm", "role", "delete", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert "resourceVersion=3" in api.requests[-1].full_url


def test_get_and_list_roles(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document())
    shown = runner.invoke(app, ["ipm", "role", "get", "--resource-id", RID])
    assert shown.exit_code == 0 and "ipm.userAdmin" in shown.stdout
    api.routes[("GET", PATH)] = Response(200, {"items": [role_document()]})
    listed = runner.invoke(app, ["ipm", "role", "list"])
    assert listed.exit_code == 0
    assert "ipm.userAdmin" in listed.stdout
    assert RID in listed.stdout  # o resourceId é o valor que o `get --resource-id` pede


def test_create_role_without_organization_fails_with_a_hint(api: FakeApi) -> None:
    result = runner.invoke(
        app,
        [
            "ipm",
            "role",
            "create",
            "--name",
            "acme.billing",
            "--description",
            "Cobrança",
            "--permission",
            "bsm.account.get",
        ],
    )
    assert result.exit_code == 2
    assert "Missing Organization" in result.stdout + result.stderr
    assert not api.requests


def test_list_roles_of_an_organization_sends_the_organization_and_shows_the_type(
    api: FakeApi,
) -> None:
    api.routes[("GET", PATH)] = Response(200, {"items": [role_document()]})
    listed = runner.invoke(app, ["ipm", "role", "list", "--organization-id", "org-acme"])
    assert listed.exit_code == 0, listed.stderr
    assert "organizationId=org-acme" in api.requests[-1].full_url
    assert "custom" in listed.stdout


def test_delete_role_still_in_use_explains_what_to_do(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document())
    api.routes[("DELETE", ROLE)] = http_error(409, "ResourcesAttached", "in use")
    result = runner.invoke(app, ["ipm", "role", "delete", "--resource-id", RID])
    assert result.exit_code != 0
    assert "users or groups" in result.stdout + result.stderr


# --- `--output json` (decisão 0093) -----------------------------------------------------------


@pytest.fixture
def default_output_mode() -> Iterator[None]:
    output.configure(raw=False)
    yield
    output.configure(raw=False)


def _document(stdout: str) -> Any:
    return json.loads(stdout)  # falha se houver mais de um documento ou texto solto


@pytest.mark.usefixtures("default_output_mode")
def test_json_get_prints_the_role_with_native_types(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document(protected=True))
    result = runner.invoke(app, [*JSON, "ipm", "role", "get", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    document = _document(result.stdout)
    assert document["resourceId"] == RID
    assert document["permissions"] == ["ipm.user.get", "ipm.user.list"]
    assert document["deletionProtection"] is True
    assert document["organizationId"] == "org-acme"
    assert "operation" not in document


@pytest.mark.usefixtures("default_output_mode")
def test_json_get_with_operation_adds_the_operation(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document())
    api.routes[("GET", OPERATION)] = operation_document("completed")
    result = runner.invoke(
        app, [*JSON, "ipm", "role", "get", "--resource-id", RID, "--operation-id", OPID]
    )
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout)["operation"]["operationStatus"] == "completed"


@pytest.mark.usefixtures("default_output_mode")
def test_json_list_prints_an_array_and_an_empty_one_without_note(api: FakeApi) -> None:
    api.routes[("GET", PATH)] = Response(200, {"items": [role_document()]})
    result = runner.invoke(app, [*JSON, "ipm", "role", "list"])
    assert result.exit_code == 0, result.stderr
    assert [item["name"] for item in _document(result.stdout)] == ["ipm.userAdmin"]
    api.routes[("GET", PATH)] = Response(200, {"items": []})
    empty = runner.invoke(app, [*JSON, "ipm", "role", "list"])
    assert empty.exit_code == 0 and _document(empty.stdout) == []


@pytest.mark.usefixtures("default_output_mode")
def test_json_delete_without_wait_prints_only_the_acceptance(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document(version="3"))
    api.routes[("DELETE", ROLE)] = accepted()
    result = runner.invoke(app, [*JSON, "ipm", "role", "delete", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout) == {"resourceId": RID, "operationId": OPID}
    assert "Follow it with" in result.stderr  # a nota não polui a saída padrão


@pytest.mark.usefixtures("default_output_mode")
def test_json_delete_with_wait_prints_a_single_document(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = [
        Response(200, role_document(version="3")),  # leitura antes do pedido
        http_error(404, "NotFound", "gone"),  # já removida
    ]
    api.routes[("DELETE", ROLE)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("completed")
    result = runner.invoke(app, [*JSON, "ipm", "role", "delete", "--resource-id", RID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout) == {"resourceId": RID, "state": "removed"}


@pytest.mark.usefixtures("default_output_mode")
def test_json_create_with_wait_prints_the_converged_role_only(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("completed")
    api.routes[("GET", ROLE)] = Response(200, role_document())
    result = runner.invoke(
        app,
        [
            *JSON,
            *["ipm", "role", "create", "--organization-id", "org-acme"],
            *["--name", "bsm.accountAdmin", "--description", "Administrador de cobrança"],
            *["--permission", "bsm.account.get", "--wait"],
        ],
    )
    assert result.exit_code == 0, result.stderr
    document = _document(result.stdout)
    assert document["resourceId"] == RID and document["phase"] == "Ready"


@pytest.mark.usefixtures("default_output_mode")
def test_json_nothing_to_do_prints_the_current_role(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document(protected=True))
    protect = runner.invoke(app, [*JSON, "ipm", "role", "protect", "--resource-id", RID])
    assert protect.exit_code == 0, protect.stderr
    document = _document(protect.stdout)
    assert document["resourceId"] == RID and document["deletionProtection"] is True
    assert "Nothing to do" in protect.stderr and "Nothing to do" not in protect.stdout
    api.routes[("GET", ROLE)] = Response(200, role_document())
    update = runner.invoke(
        app,
        [
            *JSON,
            *["ipm", "role", "update", "--resource-id", RID],
            *["--description", "Administrador de usuários"],
        ],
    )
    assert update.exit_code == 0, update.stderr
    assert _document(update.stdout)["resourceId"] == RID
    assert all(request.get_method() == "GET" for request in api.requests)  # nada foi pedido


@pytest.mark.usefixtures("default_output_mode")
def test_json_with_raw_is_compact_on_a_single_line(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document())
    result = runner.invoke(app, ["--raw", *JSON, "ipm", "role", "get", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert len(result.stdout.strip().splitlines()) == 1 and _document(result.stdout)


@pytest.mark.usefixtures("default_output_mode")
def test_json_failure_leaves_stdout_empty_and_keeps_the_exit_code(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = http_error(404, "NotFound", "missing")
    result = runner.invoke(app, [*JSON, "ipm", "role", "get", "--resource-id", RID])
    assert result.exit_code != 0 and result.stdout == "" and result.stderr != ""


@pytest.mark.usefixtures("default_output_mode")
def test_json_on_a_command_without_support_is_refused_before_acting(api: FakeApi) -> None:
    result = runner.invoke(app, [*JSON, "config", "set", "api.url", "https://x.teste"])
    assert result.exit_code == 2
    assert "no structured output" in result.stderr
    assert not api.requests


@pytest.mark.usefixtures("default_output_mode")
def test_json_escapes_control_characters_and_keeps_the_value_faithful(api: FakeApi) -> None:
    sent = "a\x1b[31m\x9b b"
    api.routes[("GET", ROLE)] = Response(200, role_document(description=sent))
    result = runner.invoke(app, [*JSON, "ipm", "role", "get", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    # Nenhum byte de controle chega ao terminal (vai escapado), e o dado não é alterado.
    assert "\x9b" not in result.stdout and "\x1b" not in result.stdout
    assert "\\u001b" in result.stdout and "\\u009b" in result.stdout
    assert _document(result.stdout)["description"] == sent


@pytest.mark.usefixtures("default_output_mode")
def test_json_nothing_to_do_on_unprotect(api: FakeApi) -> None:
    api.routes[("GET", ROLE)] = Response(200, role_document(protected=False))
    result = runner.invoke(app, [*JSON, "ipm", "role", "unprotect", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout)["resourceId"] == RID
    assert "Nothing to do" in result.stderr and "Nothing to do" not in result.stdout
    assert all(request.get_method() == "GET" for request in api.requests)
