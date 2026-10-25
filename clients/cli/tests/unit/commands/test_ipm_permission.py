"""Comandos `sk ipm permission`: pedidos, espera e saídas, contra uma API simulada."""

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
PID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
PATH = "/v1/ipm/permissions"
PERM = f"{PATH}/{PID}"
OPERATION = f"{PERM}/operations/{OPID}"


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

    monkeypatch.setattr("sk.commands.ipm_permission.time.sleep", no_wait)


def permission_document(
    *,
    phase: str = "Ready",
    name: str = "ipm.user.get",
    description: str = "Consulta usuários",
    grantable: bool = True,
    protected: bool = False,
    version: str = "1",
) -> dict[str, Any]:
    return {
        "resourceId": PID,
        "resourceVersion": version,
        "desiredGeneration": 1,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "specification": {
                "name": name,
                "description": description,
                "grantable": grantable,
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
    return Response(202, {"resourceId": PID, "operationId": OPID})


def body_of(request: urllib.request.Request) -> Any:
    return json.loads(cast(bytes, request.data))


def test_create_permission(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    result = runner.invoke(
        app,
        [
            "ipm",
            "permission",
            "create",
            "--name",
            "bsm.account.get",
            "--description",
            "Consulta conta de cobrança",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert body_of(api.requests[-1]) == {
        "name": "bsm.account.get",
        "description": "Consulta conta de cobrança",
        "grantable": True,
    }


def test_update_permission(api: FakeApi) -> None:
    api.routes[("GET", PERM)] = Response(200, permission_document(version="2"))
    api.routes[("PATCH", PERM)] = accepted()
    result = runner.invoke(
        app,
        [
            "ipm",
            "permission",
            "update",
            "--resource-id",
            PID,
            "--description",
            "Nova descrição em pt-BR",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {
        "resourceVersion": "2",
        "description": "Nova descrição em pt-BR",
    }


def test_protect_and_unprotect_permission(api: FakeApi) -> None:
    api.routes[("GET", PERM)] = [
        Response(200, permission_document(protected=False)),
        Response(200, permission_document(protected=True)),
    ]
    api.routes[("PATCH", PERM)] = accepted()
    result = runner.invoke(app, ["ipm", "permission", "protect", "--resource-id", PID])
    assert result.exit_code == 0, result.stderr
    assert body_of(api.requests[-1]) == {
        "resourceVersion": "1",
        "deletionProtection": True,
    }
    again = runner.invoke(app, ["ipm", "permission", "protect", "--resource-id", PID])
    assert again.exit_code == 0 and "Nothing to do" in again.stdout


def test_delete_permission(api: FakeApi) -> None:
    api.routes[("GET", PERM)] = Response(200, permission_document(version="3"))
    api.routes[("DELETE", PERM)] = accepted()
    result = runner.invoke(app, ["ipm", "permission", "delete", "--resource-id", PID])
    assert result.exit_code == 0, result.stderr
    assert "resourceVersion=3" in api.requests[-1].full_url


def test_get_and_list_permissions(api: FakeApi) -> None:
    api.routes[("GET", PERM)] = Response(200, permission_document())
    shown = runner.invoke(app, ["ipm", "permission", "get", "--resource-id", PID])
    assert shown.exit_code == 0 and "ipm.user.get" in shown.stdout
    api.routes[("GET", PATH)] = Response(200, {"items": [permission_document()]})
    listed = runner.invoke(app, ["ipm", "permission", "list"])
    assert listed.exit_code == 0 and PID in listed.stdout
