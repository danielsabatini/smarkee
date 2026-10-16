"""`sk account get|delete`: a conta da sessão e a exclusão segura (decisão 0040)."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sk.features.core.account import token_subject
from sk.identity.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.main import app

runner = CliRunner()
API = "https://api.teste"
ME = "01a14168-b59d-7475-8db7-c5cf57fa100b"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
USER = f"/v1/core/accounts/{ME}"
OPERATION = f"{USER}/operations/{OPID}"


def jwt_for(subject: str) -> str:
    def part(document: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(document).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'sub': subject})}.assinatura"


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
    """Substitui `urlopen`: responde por (método, caminho); uma lista responde em sequência."""

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


def http_error(status: int, error_code: str, message: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"errorCode": error_code, "message": message}).encode())
    return urllib.error.HTTPError(API, status, message, hdrs=None, fp=body)  # type: ignore[arg-type]


def no_wait(_: float) -> None:
    return None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeApi]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("SK_API_URL", raising=False)
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(f'[api]\nurl = "{API}"\n', encoding="utf-8")
    fake = FakeApi()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr("sk.commands.account.time.sleep", no_wait)
    save_credentials(
        default_credentials_path(),
        StoredCredentials(
            issuer="https://ipm.teste",
            client_id="cli",
            token_type="Bearer",
            access_token=jwt_for(ME),
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_token="refresh-1",
            id_token=None,
            scope="openid",
            obtained_at=datetime.now(UTC),
        ),
    )
    yield fake


def user_document(version: str = "3", *, protected: bool = True) -> dict[str, Any]:
    return {
        "resourceId": ME,
        "resourceVersion": version,
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "platformAccess": "granted",
            "givenName": "Ana",
            "familyName": "Souza",
            "email": "ana@example.com",
            "deletionProtection": protected,
        },
    }


def operation(status: str) -> Response:
    return Response(200, {"operationId": OPID, "operationStatus": status})


def accepted() -> Response:
    return Response(202, {"resourceId": ME, "operationId": OPID})


def test_the_subject_is_read_from_the_session_token() -> None:
    assert token_subject(jwt_for(ME)) == ME


@pytest.mark.parametrize("token", ["", "a.b", "a.b.c", f"x.{jwt_for('A/../')[5:]}"])
def test_an_unreadable_token_or_subject_is_refused(token: str) -> None:
    with pytest.raises(ValueError):
        token_subject(token)


def test_get_shows_the_account_of_the_session(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())

    result = runner.invoke(app, ["account", "get"])

    assert result.exit_code == 0, result.stdout + result.stderr
    for text in ("Ana Souza", "ana@example.com", "Ready", "granted", ME):
        assert text in result.stdout


def test_get_without_a_session_asks_for_login(api: FakeApi) -> None:
    default_credentials_path().unlink()

    result = runner.invoke(app, ["account", "get"])

    assert result.exit_code == 1
    assert "sk auth login" in result.stderr
    assert api.requests == []


def test_delete_requires_the_confirmation_before_any_call(api: FakeApi) -> None:
    result = runner.invoke(app, ["account", "delete"])

    assert result.exit_code == 2
    assert "--yes" in result.stderr
    assert api.requests == []


def test_delete_reads_the_version_and_sends_it_with_an_idempotency_key(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(version="9"))
    api.routes[("DELETE", USER)] = accepted()

    result = runner.invoke(app, ["account", "delete", "--yes"])

    assert result.exit_code == 0, result.stdout + result.stderr
    delete = next(request for request in api.requests if request.get_method() == "DELETE")
    assert "resourceVersion=9" in delete.full_url
    assert delete.get_header("Idempotency-key")
    assert default_credentials_path().exists()  # sem --wait, a sessão fica até a conta sumir


def test_delete_is_refused_while_resources_are_attached_and_says_what_to_remove(
    api: FakeApi,
) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("DELETE", USER)] = http_error(
        409, "ResourcesAttached", "A conta tem recursos atrelados: 1 Organization. Remova-os."
    )

    result = runner.invoke(app, ["account", "delete", "--yes"])

    assert result.exit_code == 1
    text = " ".join(result.stderr.split())
    assert "sk ipm organization delete" in text and "sk sum service disable" in text
    assert default_credentials_path().exists()


def test_delete_when_a_module_cannot_be_verified_points_to_renewing_the_session(
    api: FakeApi,
) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("DELETE", USER)] = http_error(409, "ResourcesNotVerifiable", "sem permissão")

    result = runner.invoke(app, ["account", "delete", "--yes"])

    assert result.exit_code == 1
    assert "sk auth refresh" in " ".join(result.stderr.split())


def test_delete_wait_ends_when_the_operation_completes_and_forgets_the_session(
    api: FakeApi,
) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("DELETE", USER)] = accepted()
    api.routes[("GET", OPERATION)] = [operation("in_progress"), operation("completed")]

    result = runner.invoke(app, ["account", "delete", "--yes", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Account deleted" in result.stdout
    assert not default_credentials_path().exists()


def test_delete_wait_also_ends_when_the_token_stops_being_accepted(api: FakeApi) -> None:
    """Com o usuário removido do provedor, o fim da exclusão aparece como `401`."""
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("DELETE", USER)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation("in_progress"),
        http_error(401, "Unauthorized", "Token ausente ou inválido."),
    ]

    result = runner.invoke(app, ["account", "delete", "--yes", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert not default_credentials_path().exists()


def test_delete_wait_times_out_without_forgetting_the_session(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("DELETE", USER)] = accepted()
    api.routes[("GET", OPERATION)] = operation("in_progress")
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr("sk.commands.account.time.monotonic", lambda: next(clock))

    result = runner.invoke(app, ["account", "delete", "--yes", "--wait", "--timeout", "30"])

    assert result.exit_code == 1
    assert "Timed out" in result.stderr
    assert default_credentials_path().exists()


def test_unprotect_sends_the_flag_with_the_current_version(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(version="5"))
    api.routes[("PATCH", USER)] = accepted()

    result = runner.invoke(app, ["account", "unprotect"])

    assert result.exit_code == 0, result.stdout + result.stderr
    patch = next(request for request in api.requests if request.get_method() == "PATCH")
    assert json.loads(patch.data) == {"resourceVersion": "5", "deletionProtection": False}  # type: ignore[arg-type]
    assert patch.get_header("Idempotency-key")


def test_protect_is_idempotent_when_already_protected(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(protected=True))

    result = runner.invoke(app, ["account", "protect"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "already protected" in " ".join(result.stdout.split())
    assert [request.get_method() for request in api.requests] == ["GET"]


def test_unprotect_wait_ends_when_the_operation_completes(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("PATCH", USER)] = accepted()
    api.routes[("GET", OPERATION)] = [operation("in_progress"), operation("completed")]

    result = runner.invoke(app, ["account", "unprotect", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Account unprotected" in result.stdout


def test_get_shows_whether_the_account_is_protected(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document(protected=False))

    result = runner.invoke(app, ["account", "get"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "protected" in result.stdout


def test_delete_of_a_protected_account_points_to_unprotect(api: FakeApi) -> None:
    api.routes[("GET", USER)] = Response(200, user_document())
    api.routes[("DELETE", USER)] = http_error(
        409, "DeletionProtected", "A conta está protegida contra exclusão."
    )

    result = runner.invoke(app, ["account", "delete", "--yes"])

    assert result.exit_code == 1
    assert "sk account unprotect" in " ".join(result.stderr.split())
