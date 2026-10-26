"""Comandos `sk ipm group`: pedidos, espera e saídas, contra uma API simulada."""

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
ORG = "01a15e61-6d1e-7096-878a-d5f450b858f1"
RID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
PATH = "/v1/ipm/groups"
GROUP = f"{PATH}/{RID}"
OPERATION = f"{GROUP}/operations/{OPID}"


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


def group_document(
    *,
    phase: str = "Ready",
    name: str = "devops",
    description: str = "Time de DevOps",
    roles: list[str] | None = None,
    protected: bool = False,
    version: str = "1",
) -> dict[str, Any]:
    roles = roles or ["ipm.userViewer"]
    return {
        "resourceId": RID,
        "resourceVersion": version,
        "desiredGeneration": 1,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "organizationId": ORG,
            "specification": {
                "name": name,
                "description": description,
                "roles": roles,
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


def test_create_group(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = Response(202, {"resourceId": RID, "operationId": OPID})
    result = runner.invoke(
        app,
        [
            "ipm",
            "group",
            "create",
            "--organization-id",
            ORG,
            "--name",
            "devops",
            "--description",
            "Time de DevOps",
            "--role",
            "ipm.userViewer",
        ],
    )
    assert result.exit_code == 0
    assert "Creation requested" in result.output
    body = json.loads(cast(bytes, api.requests[0].data))
    assert body["name"] == "devops"
    assert body["roles"] == ["ipm.userViewer"]


def test_get_group(api: FakeApi) -> None:
    api.routes[("GET", GROUP)] = Response(200, group_document())
    result = runner.invoke(app, ["ipm", "group", "get", "--resource-id", RID])
    assert result.exit_code == 0
    assert "devops" in result.output
    assert "Time de DevOps" in result.output


def test_list_groups(api: FakeApi) -> None:
    api.routes[("GET", PATH)] = Response(200, {"items": [group_document()]})
    result = runner.invoke(app, ["ipm", "group", "list", "--organization-id", ORG])
    assert result.exit_code == 0
    assert "devops" in result.output


def test_delete_group(api: FakeApi) -> None:
    api.routes[("GET", GROUP)] = Response(200, group_document(version="3"))
    api.routes[("DELETE", GROUP)] = Response(202, {"resourceId": RID, "operationId": OPID})
    result = runner.invoke(app, ["ipm", "group", "delete", "--resource-id", RID])
    assert result.exit_code == 0
    assert "Deletion requested" in result.output


def test_update_group(api: FakeApi) -> None:
    api.routes[("GET", GROUP)] = Response(200, group_document(version="1"))
    api.routes[("PATCH", GROUP)] = Response(202, {"resourceId": RID, "operationId": OPID})
    result = runner.invoke(
        app,
        [
            "ipm",
            "group",
            "update",
            "--resource-id",
            RID,
            "--description",
            "Nova descrição",
            "--role",
            "ipm.groupViewer",
        ],
    )
    assert result.exit_code == 0
    assert "Change requested" in result.output


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
    api.routes[("GET", GROUP)] = Response(
        200, group_document(roles=["ipm.userViewer"], protected=True)
    )
    shown = runner.invoke(app, [*JSON, "ipm", "group", "get", "--resource-id", RID])
    assert shown.exit_code == 0, shown.stderr
    document = _document(shown.stdout)
    assert document["roles"] == ["ipm.userViewer"] and document["deletionProtection"] is True
    api.routes[("GET", PATH)] = Response(200, {"items": [group_document()]})
    listed = runner.invoke(app, [*JSON, "ipm", "group", "list", "--organization-id", ORG])
    assert [g["name"] for g in _document(listed.stdout)] == ["devops"]
    api.routes[("GET", PATH)] = Response(200, {"items": []})
    empty = runner.invoke(app, [*JSON, "ipm", "group", "list", "--organization-id", ORG])
    assert _document(empty.stdout) == []


@pytest.mark.usefixtures("default_output_mode")
def test_json_delete_prints_only_the_acceptance_and_nothing_to_do_prints_the_group(
    api: FakeApi,
) -> None:
    api.routes[("GET", GROUP)] = Response(200, group_document(version="3"))
    api.routes[("DELETE", GROUP)] = Response(202, {"resourceId": RID, "operationId": OPID})
    deleted = runner.invoke(app, [*JSON, "ipm", "group", "delete", "--resource-id", RID])
    assert deleted.exit_code == 0, deleted.stderr
    assert _document(deleted.stdout) == {"resourceId": RID, "operationId": OPID}
    api.routes[("GET", GROUP)] = Response(200, group_document(protected=True))
    again = runner.invoke(app, [*JSON, "ipm", "group", "protect", "--resource-id", RID])
    assert again.exit_code == 0, again.stderr
    assert _document(again.stdout)["resourceId"] == RID and "Nothing to do" in again.stderr


@pytest.mark.usefixtures("default_output_mode")
def test_json_on_an_unsupported_command_is_refused_before_acting(api: FakeApi) -> None:
    result = runner.invoke(app, [*JSON, "auth", "refresh"])
    assert result.exit_code == 2 and "no structured output" in result.stderr
    assert not api.requests


@pytest.mark.usefixtures("default_output_mode")
def test_json_delete_with_wait_prints_the_removed_state(api: FakeApi) -> None:
    api.routes[("GET", GROUP)] = [
        Response(200, group_document(version="3")),  # leitura antes do pedido
        http_error(404, "NotFound", "gone"),  # já removido
    ]
    api.routes[("DELETE", GROUP)] = Response(202, {"resourceId": RID, "operationId": OPID})
    api.routes[("GET", OPERATION)] = operation_document("completed")
    result = runner.invoke(app, [*JSON, "ipm", "group", "delete", "--resource-id", RID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout) == {"resourceId": RID, "state": "removed"}


@pytest.mark.usefixtures("default_output_mode")
def test_json_get_with_operation_adds_the_operation(api: FakeApi) -> None:
    api.routes[("GET", GROUP)] = Response(200, group_document())
    api.routes[("GET", OPERATION)] = operation_document("completed")
    result = runner.invoke(
        app, [*JSON, "ipm", "group", "get", "--resource-id", RID, "--operation-id", OPID]
    )
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout)["operation"]["operationStatus"] == "completed"
