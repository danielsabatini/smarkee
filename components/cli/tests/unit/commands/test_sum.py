"""Comandos `sk sum service`: pedidos à API, sessão, validação e mensagens de saída."""

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
RID = "01a14168-b59d-7475-8db7-c5cf57fa100b"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"


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
        self.routes: dict[tuple[str, str], Response | urllib.error.HTTPError] = {}
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Response:
        self.requests.append(request)
        path = request.full_url.removeprefix(API)
        key = (request.get_method(), path.split("?")[0])
        found = self.routes.get(key)
        if found is None:
            raise AssertionError(f"rota não prevista: {key}")
        if isinstance(found, urllib.error.HTTPError):
            raise found
        return found


def http_error(status: int, error_code: str, message: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"errorCode": error_code, "message": message}).encode())
    return urllib.error.HTTPError(API, status, message, hdrs=None, fp=body)  # type: ignore[arg-type]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeApi]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("SK_CORE_API_URL", raising=False)
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(f'[core]\napiUrl = "{API}"\n', encoding="utf-8")
    fake = FakeApi()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    save_credentials(default_credentials_path(), session(datetime.now(UTC) + timedelta(hours=1)))
    yield fake


def session(
    expires_at: datetime,
    refresh_token: str | None = "refresh-1",  # noqa: S107 (token falso de teste)
) -> StoredCredentials:
    return StoredCredentials(
        issuer="https://ipm.teste",
        client_id="cli",
        token_type="Bearer",
        access_token="access-1",
        access_token_expires_at=expires_at,
        refresh_token=refresh_token,
        id_token=None,
        scope="openid",
        obtained_at=datetime.now(UTC),
    )


def link_document(lifecycle: str = "present", phase: str = "Ready") -> dict[str, Any]:
    return {
        "resourceId": RID,
        "resourceVersion": "3",
        "desiredGeneration": 2,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": lifecycle,
            "service": "ipm",
            "serviceRoles": ["ipm.organization.get"],
        },
        "observed": {"serviceRoles": ["ipm.organization.get"] if lifecycle == "present" else []},
        "createdAt": "2026-10-15T20:00:00+00:00",
        "updatedAt": "2026-10-15T20:00:05+00:00",
    }


def test_enable_sends_the_service_with_the_session_token_and_an_idempotency_key(
    api: FakeApi,
) -> None:
    api.routes[("POST", "/v1/sum/services")] = Response(
        202, {"resourceId": RID, "operationId": OPID}
    )
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 0, result.stdout
    request = api.requests[-1]
    assert request.get_header("Authorization") == "Bearer access-1"
    assert request.get_header("Idempotency-key")
    body = cast(bytes, request.data)
    assert json.loads(body) == {"service": "ipm"}
    assert RID in result.stdout and OPID in result.stdout


def test_enable_requires_the_service_option(api: FakeApi) -> None:
    result = runner.invoke(app, ["sum", "service", "enable"])
    assert result.exit_code == 2
    assert api.requests == []


def test_disable_reads_the_version_before_deleting(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("DELETE", f"/v1/sum/services/{RID}")] = Response(
        202, {"resourceId": RID, "operationId": OPID}
    )
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 0, result.stdout
    delete = api.requests[-1]
    assert delete.full_url.endswith(f"/v1/sum/services/{RID}?resourceVersion=3")


def test_disable_of_a_link_that_is_already_off_is_a_no_op(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document("absent", "Ready"))
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 0
    assert "já está desligada" in result.stdout
    assert all(request.get_method() != "DELETE" for request in api.requests)


def test_get_shows_the_phase_and_the_operation_status(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("GET", f"/v1/sum/services/{RID}/operations/{OPID}")] = Response(
        200, {"operationId": OPID, "operationStatus": "completed"}
    )
    result = runner.invoke(
        app, ["sum", "service", "get", "--resource-id", RID, "--operation-id", OPID]
    )
    assert result.exit_code == 0, result.stdout
    assert "Ready" in result.stdout and "completed" in result.stdout


def test_list_prints_one_row_per_link(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": [link_document()]})
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 0, result.stdout
    assert RID in result.stdout


def test_an_empty_list_says_so(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": []})
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 0
    assert "Nenhuma ligação" in result.stdout


def test_a_refused_request_shows_the_api_reason_and_a_hint(api: FakeApi) -> None:
    api.routes[("POST", "/v1/sum/services")] = http_error(403, "Forbidden", "sem permissão")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert "sem permissão" in result.stderr


def test_a_conflict_on_disable_asks_to_read_again(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("DELETE", f"/v1/sum/services/{RID}")] = http_error(409, "Conflict", "mudou")
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 1
    assert "A ligação mudou desde a última leitura" in result.stderr


def test_a_server_failure_is_reported_as_unavailable(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = http_error(503, "Unavailable", "fora")
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 1
    assert "indisponível" in result.stderr


def test_without_a_session_the_command_asks_for_login(api: FakeApi, tmp_path: Path) -> None:
    default_credentials_path().unlink()
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 1
    assert "sk auth login" in result.stderr
    assert api.requests == []


def test_plain_http_is_refused_without_permission(api: FakeApi, tmp_path: Path) -> None:
    (tmp_path / "sk" / "config.toml").write_text(
        '[core]\napiUrl = "http://api.teste"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 2
    assert "Endereço da API recusado" in result.stderr
    assert api.requests == []


def test_the_api_address_and_the_http_permission_come_from_the_command_line(
    api: FakeApi,
) -> None:
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": []})
    result = runner.invoke(app, ["sum", "service", "list", "--api-url", API])
    assert result.exit_code == 0, result.stderr
    result = runner.invoke(
        app, ["sum", "service", "list", "--api-url", "http://api.teste", "--allow-insecure-http"]
    )
    assert "Endereço da API recusado" not in result.stderr  # a permissão foi aceita


def test_without_an_api_address_the_command_asks_for_it(api: FakeApi, tmp_path: Path) -> None:
    (tmp_path / "sk" / "config.toml").write_text("", encoding="utf-8")
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 2
    assert "API não informada" in result.stderr
    assert api.requests == []


@pytest.mark.parametrize(
    "bad_id", ["../../admin", "a/b", f"{RID}?x=1", f"{RID}#", "", " ", "{" + RID + "}", "abc"]
)
def test_an_identifier_that_is_not_a_uuid_is_refused_before_any_call(
    api: FakeApi, bad_id: str
) -> None:
    for command in (
        ["disable", "--resource-id", bad_id],
        ["get", "--resource-id", bad_id],
        ["get", "--resource-id", RID, "--operation-id", bad_id],
    ):
        result = runner.invoke(app, ["sum", "service", *command])
        assert result.exit_code == 2, command
        assert "Dados não aceitos" in result.stderr
        assert bad_id.strip() == "" or bad_id not in result.stderr  # o valor não é repetido
    assert api.requests == []


def test_an_uppercase_uuid_is_sent_in_the_canonical_lowercase_form(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    result = runner.invoke(app, ["sum", "service", "get", "--resource-id", RID.upper()])
    assert result.exit_code == 0, result.stderr
    assert api.requests[-1].full_url.endswith(f"/v1/sum/services/{RID}")


def test_too_many_requests_shows_the_wait_time(api: FakeApi) -> None:
    body = io.BytesIO(json.dumps({"errorCode": "RateLimited", "message": "limite"}).encode())
    headers = cast(Any, {"Retry-After": "30"})
    api.routes[("POST", "/v1/sum/services")] = urllib.error.HTTPError(
        API, 429, "limite", hdrs=headers, fp=body
    )
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert "Aguarde 30 segundos" in result.stderr


def test_a_validation_error_names_the_field_and_exits_with_usage_code(api: FakeApi) -> None:
    body = io.BytesIO(
        json.dumps(
            {"errorCode": "ValidationFailed", "message": "valor inválido", "field": "service"}
        ).encode()
    )
    api.routes[("POST", "/v1/sum/services")] = urllib.error.HTTPError(
        API, 400, "x", hdrs=cast(Any, {}), fp=body
    )
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 2
    assert "service: valor inválido" in result.stderr


def test_a_missing_operation_is_not_reported_as_a_missing_link(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("GET", f"/v1/sum/services/{RID}/operations/{OPID}")] = http_error(
        404, "NotFound", "não existe"
    )
    result = runner.invoke(
        app, ["sum", "service", "get", "--resource-id", RID, "--operation-id", OPID]
    )
    assert result.exit_code == 1
    assert "Operation não encontrada" in result.stderr
    assert "Ligação não encontrada" not in result.stderr


def test_a_missing_link_says_so(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = http_error(404, "NotFound", "não existe")
    result = runner.invoke(app, ["sum", "service", "get", "--resource-id", RID])
    assert result.exit_code == 1
    assert "Ligação não encontrada" in result.stderr


def test_the_token_never_appears_in_the_output(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = http_error(403, "Forbidden", "sem permissão")
    result = runner.invoke(app, ["sum", "service", "list"])
    assert "access-1" not in result.stdout + result.stderr
