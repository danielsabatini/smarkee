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

from sk import output
from sk.defaults import PRD_API_URL
from sk.identity.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.main import app

runner = CliRunner()
API = "https://api.teste"
RID = "01a14168-b59d-7475-8db7-c5cf57fa100b"


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
        # Uma lista responde em sequência; a última resposta se repete.
        self.routes: dict[
            tuple[str, str],
            Response | urllib.error.HTTPError | list[Response | urllib.error.HTTPError],
        ] = {}
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Response:
        self.requests.append(request)
        path = request.full_url.removeprefix(API)
        key = (request.get_method(), path.split("?")[0])
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


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeApi]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("SK_API_URL", raising=False)
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(f'[api]\nurl = "{API}"\n', encoding="utf-8")
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


def link_document(
    lifecycle: str = "present",
    phase: str = "Ready",
    *,
    desired_generation: int = 2,
    observed_generation: int | None = 2,
    conditions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "resourceId": RID,
        "resourceVersion": "3",
        "desiredGeneration": desired_generation,
        "observedGeneration": observed_generation,
        "phase": phase,
        "conditions": conditions or [],
        "desired": {
            "lifecycle": lifecycle,
            "service": "ipm",
            "servicePermissions": ["ipm.organization.get"],
        },
        "observed": {
            "servicePermissions": ["ipm.organization.get"] if lifecycle == "present" else []
        },
        "createdAt": "2026-10-15T20:00:00+00:00",
        "updatedAt": "2026-10-15T20:00:05+00:00",
    }


def test_enable_sends_the_service_with_the_session_token_and_an_idempotency_key(
    api: FakeApi,
) -> None:
    api.routes[("POST", "/v1/sum/services")] = Response(201, link_document("present", "Pending"))
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 0, result.stdout
    request = api.requests[-1]
    assert request.get_header("Authorization") == "Bearer access-1"
    assert request.get_header("Idempotency-key")
    body = cast(bytes, request.data)
    assert json.loads(body) == {"service": "ipm"}
    assert RID in result.stdout and "Pending" in result.stdout


def test_enable_requires_the_service_option(api: FakeApi) -> None:
    result = runner.invoke(app, ["sum", "service", "enable"])
    assert result.exit_code == 2
    assert api.requests == []


def test_disable_reads_the_version_before_deleting(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("DELETE", f"/v1/sum/services/{RID}")] = Response(
        202, link_document("absent", "Reconciling", desired_generation=3, observed_generation=2)
    )
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 0, result.stdout
    delete = api.requests[-1]
    assert delete.full_url.endswith(f"/v1/sum/services/{RID}?resourceVersion=3")


def test_disable_of_a_link_that_is_already_off_is_a_no_op(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document("absent", "Ready"))
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 0
    assert "is already disabled" in result.stdout
    assert all(request.get_method() != "DELETE" for request in api.requests)


def test_get_shows_the_state_and_the_phase(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    result = runner.invoke(app, ["sum", "service", "get", "--resource-id", RID])
    assert result.exit_code == 0, result.stdout
    assert "Ready" in result.stdout and "enabled" in result.stdout


def test_get_no_longer_accepts_an_operation(api: FakeApi) -> None:
    result = runner.invoke(
        app, ["sum", "service", "get", "--resource-id", RID, "--operation-id", RID]
    )
    assert result.exit_code == 2 and "No such option" in result.output
    assert api.requests == []


def test_list_prints_one_row_per_link(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": [link_document()]})
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 0, result.stdout
    assert RID in result.stdout


def test_an_empty_list_says_so(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": []})
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 0
    assert "No services" in result.stdout


def test_a_refused_request_shows_only_the_cli_message_in_english(api: FakeApi) -> None:
    api.routes[("POST", "/v1/sum/services")] = http_error(403, "Forbidden", "sem permissão")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert "does not have permission" in result.stderr
    assert "sem permissão" not in result.stderr  # o texto do servidor (pt-BR) não se mistura


def test_a_refusal_without_a_cli_message_shows_the_server_text(api: FakeApi) -> None:
    api.routes[("POST", "/v1/sum/services")] = http_error(422, "IdempotencyKeyReused", "reusada")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert "reusada" in result.stderr and "HTTP 422 (IdempotencyKeyReused)" in result.stderr


def test_a_conflict_on_disable_asks_to_read_again(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("DELETE", f"/v1/sum/services/{RID}")] = http_error(409, "Conflict", "mudou")
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 1
    assert "The service changed since it was last read" in result.stderr


def test_a_conflict_on_enable_points_to_the_existing_link(api: FakeApi) -> None:
    api.routes[("POST", "/v1/sum/services")] = http_error(409, "AlreadyEnabled", "já ligado")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert "This service is already enabled" in result.stderr
    assert "changed since it was last read" not in result.stderr


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        (409, "ServiceNotAvailable", "This service is not available"),
        (409, "BillingAccountRequired", "sk bsm account create"),
    ],
)
def test_the_enable_refusals_of_the_api_have_their_own_hint(
    api: FakeApi, status: int, error_code: str, expected: str
) -> None:
    api.routes[("POST", "/v1/sum/services")] = http_error(status, error_code, "texto do servidor")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert expected in " ".join(result.stderr.split())


def test_a_server_failure_is_reported_as_unavailable(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = http_error(503, "Unavailable", "fora")
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 1
    assert "unavailable" in result.stderr


def test_without_a_session_the_command_asks_for_login(api: FakeApi, tmp_path: Path) -> None:
    default_credentials_path().unlink()
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 1
    assert "sk auth login" in result.stderr
    assert api.requests == []


def test_plain_http_is_refused_without_permission(api: FakeApi, tmp_path: Path) -> None:
    (tmp_path / "sk" / "config.toml").write_text(
        '[api]\nurl = "http://api.teste"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 2
    assert "API address refused" in result.stderr
    assert api.requests == []


def test_the_api_address_comes_from_the_environment(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": []})
    monkeypatch.setenv("SK_API_URL", API)
    result = runner.invoke(app, ["sum", "service", "list"])
    assert result.exit_code == 0, result.stderr


def test_the_environment_options_do_not_exist_on_the_command_line(api: FakeApi) -> None:
    """Endereço e permissão de HTTP são do ambiente (decisão 0041), e não de opções."""
    for option in (["--api-url", API], ["--allow-insecure-http"], ["--issuer", API]):
        result = runner.invoke(app, ["sum", "service", "list", *option])
        assert result.exit_code == 2 and "No such option" in result.output, option


def test_http_without_tls_is_allowed_only_by_environment(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SK_API_URL", "http://api.teste")
    refused = runner.invoke(app, ["sum", "service", "list"])
    assert refused.exit_code == 2
    assert "SK_API_ALLOW_INSECURE_HTTP=true" in " ".join(refused.stderr.split())

    monkeypatch.setenv("SK_API_ALLOW_INSECURE_HTTP", "true")
    allowed = runner.invoke(app, ["sum", "service", "list"])
    assert "API address refused" not in allowed.stderr


def test_without_any_configuration_the_command_uses_the_production_api(
    api: FakeApi, tmp_path: Path
) -> None:
    (tmp_path / "sk" / "config.toml").write_text("", encoding="utf-8")
    runner.invoke(app, ["sum", "service", "list"])  # a rota de teste não existe: só o alvo importa
    assert api.requests[0].full_url.startswith(f"{PRD_API_URL}/v1/sum/services")


@pytest.mark.parametrize(
    "bad_id",
    ["../../admin", "..", "a/b", f"{RID}?x=1", f"{RID}#", "", " ", RID.upper(), "a" * 129],
)
def test_an_identifier_outside_the_contract_is_refused_before_any_call(
    api: FakeApi, bad_id: str
) -> None:
    for command in (
        ["disable", "--resource-id", bad_id],
        ["get", "--resource-id", bad_id],
    ):
        result = runner.invoke(app, ["sum", "service", *command])
        assert result.exit_code == 2, command
        assert "Value not accepted" in result.stderr
        assert bad_id.strip() == "" or bad_id not in result.stderr  # o valor não é repetido
    assert api.requests == []


def test_an_opaque_identifier_that_is_not_a_uuid_is_accepted_and_sent_as_it_is(
    api: FakeApi,
) -> None:
    api.routes[("GET", "/v1/sum/services/ligacao-42")] = Response(200, link_document())
    result = runner.invoke(app, ["sum", "service", "get", "--resource-id", "ligacao-42"])
    assert result.exit_code == 0, result.stderr
    assert api.requests[-1].full_url.endswith("/v1/sum/services/ligacao-42")


def test_too_many_requests_shows_the_wait_time(api: FakeApi) -> None:
    body = io.BytesIO(json.dumps({"errorCode": "RateLimited", "message": "limite"}).encode())
    headers = cast(Any, {"Retry-After": "30"})
    api.routes[("POST", "/v1/sum/services")] = urllib.error.HTTPError(
        API, 429, "limite", hdrs=headers, fp=body
    )
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 1
    assert "Wait 30 seconds" in result.stderr


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


def test_a_missing_link_says_so(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = http_error(404, "NotFound", "não existe")
    result = runner.invoke(app, ["sum", "service", "get", "--resource-id", RID])
    assert result.exit_code == 1
    assert "Service not found" in result.stderr


def test_the_token_never_appears_in_the_output(api: FakeApi) -> None:
    api.routes[("GET", "/v1/sum/services")] = http_error(403, "Forbidden", "sem permissão")
    result = runner.invoke(app, ["sum", "service", "list"])
    assert "access-1" not in result.stdout + result.stderr


# ------------------------------------------------------------- --wait e a renovação da sessão


def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def renewals(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Troca a renovação da sessão por um registro e a espera por nada (o teste não dorme)."""
    calls: list[bool] = []

    def record(*_: object, **__: object) -> None:
        calls.append(True)

    monkeypatch.setattr("sk.commands.shared.renew_session", record)
    monkeypatch.setattr("sk.commands.shared.time.sleep", no_sleep)
    return calls


def route_admitted(api: FakeApi, method: str) -> None:
    """A API admite o pedido: a geração nova (2 ou 3) ainda não foi observada."""
    if method == "POST":
        api.routes[("POST", "/v1/sum/services")] = Response(
            201, link_document("present", "Pending", observed_generation=None)
        )
    else:
        api.routes[("DELETE", f"/v1/sum/services/{RID}")] = Response(
            202, link_document("absent", "Reconciling", desired_generation=3, observed_generation=2)
        )


def test_enable_wait_waits_for_ready_then_renews_the_session(
    api: FakeApi, renewals: list[bool]
) -> None:
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = [
        Response(200, link_document("present", "Reconciling", observed_generation=1)),
        Response(200, link_document("present", "Ready")),
    ]
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Service enabled" in result.stdout
    assert "enabled" in result.stdout and "Ready" in result.stdout
    assert "renewed" in result.stdout
    assert renewals == [True]


def test_wait_does_not_stop_at_a_ready_phase_of_an_older_generation(
    api: FakeApi, renewals: list[bool]
) -> None:
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = [
        Response(200, link_document("present", "Ready", observed_generation=1)),
        Response(200, link_document("present", "Ready")),
    ]
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert len([r for r in api.requests if r.get_method() == "GET"]) == 2


def test_wait_asks_for_a_fresh_token_on_every_poll(
    api: FakeApi, renewals: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """O acesso dura 15 minutos: uma espera longa pode atravessar o vencimento."""
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = [
        Response(200, link_document("present", "Reconciling", observed_generation=1)),
        Response(200, link_document("present", "Reconciling", observed_generation=1)),
        Response(200, link_document("present", "Ready")),
    ]
    asked: list[bool] = []

    def counting_token(*_: object, **__: object) -> str:
        asked.append(True)
        return "access-1"

    monkeypatch.setattr("sk.commands.shared.current_access_token", counting_token)
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(asked) >= 4  # o pedido de ligar e uma vez por leitura (3)


def test_enable_without_wait_does_not_poll_nor_renew_and_points_to_refresh(
    api: FakeApi, renewals: list[bool]
) -> None:
    route_admitted(api, "POST")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 0, result.stderr
    assert "sk auth refresh" in result.stdout
    assert [request.get_method() for request in api.requests] == ["POST"]
    assert renewals == []


def test_wait_times_out_with_a_hint_and_does_not_renew(
    api: FakeApi, renewals: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(
        200, link_document("present", "Reconciling", observed_generation=1)
    )
    clock = iter(range(0, 1000, 20))  # cada leitura do relógio avança 20 s
    monkeypatch.setattr("sk.commands.shared.time.monotonic", lambda: next(clock))
    result = runner.invoke(
        app, ["sum", "service", "enable", "--service", "ipm", "--wait", "--timeout", "30"]
    )
    assert result.exit_code == 1
    assert "Timed out" in result.stderr and "Reconciling" in result.stderr
    assert "sk sum service get" in result.stderr
    assert RID in result.stderr
    assert renewals == []


def test_wait_stops_when_the_link_ends_in_failed(api: FakeApi, renewals: list[bool]) -> None:
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(
        200,
        link_document(
            "present",
            "Failed",
            conditions=[{"status": "False", "reason": "ProviderUnavailable"}],
        ),
    )
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 1
    assert "Request not completed" in result.stderr and "ProviderUnavailable" in result.stderr
    assert renewals == []


def test_a_missing_link_during_the_wait_is_an_error(api: FakeApi, renewals: list[bool]) -> None:
    """Ligar e desligar não removem o registro (religar reaproveita o `resourceId`)."""
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = http_error(404, "NotFound", "não existe")
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 1
    assert "Service not found" in result.stderr
    assert renewals == []


def test_a_failed_renewal_is_a_warning_not_a_failure(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sk.identity.session import SessionError

    def fail(*_: object, **__: object) -> None:
        raise SessionError("A sessão não tem refresh token.")

    monkeypatch.setattr("sk.commands.shared.renew_session", fail)
    monkeypatch.setattr("sk.commands.shared.time.sleep", no_sleep)
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    result = runner.invoke(app, ["sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 0, result.stderr
    assert "not renewed" in result.stdout
    assert "sk auth login" in result.stderr  # o aviso


def test_disable_wait_waits_for_the_disabled_state_and_renews(
    api: FakeApi, renewals: list[bool]
) -> None:
    route_admitted(api, "DELETE")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = [
        Response(200, link_document("present", "Ready")),  # a leitura que antecede o pedido
        Response(
            200, link_document("absent", "Reconciling", desired_generation=3, observed_generation=2)
        ),
        Response(
            200, link_document("absent", "Ready", desired_generation=3, observed_generation=3)
        ),
    ]
    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID, "--wait"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Service disabled" in result.stdout and "disabled" in result.stdout
    assert renewals == [True]


def test_the_state_is_shown_in_english(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document("absent", "Ready"))
    shown = runner.invoke(app, ["sum", "service", "get", "--resource-id", RID])
    assert "disabled" in shown.stdout and "desabilitado" not in shown.stdout
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": [link_document()]})
    listed = runner.invoke(app, ["sum", "service", "list"])
    assert "Ready" in listed.stdout


def test_disable_refused_while_organizations_exist_says_what_to_delete(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    api.routes[("DELETE", f"/v1/sum/services/{RID}")] = http_error(
        409, "ResourcesAttached", "O serviço ipm tem 1 recurso(s) atrelado(s)."
    )

    result = runner.invoke(app, ["sum", "service", "disable", "--resource-id", RID])

    assert result.exit_code == 1
    assert "sk ipm organization delete" in " ".join(result.stderr.split())


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
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    shown = runner.invoke(app, [*JSON, "sum", "service", "get", "--resource-id", RID])
    assert shown.exit_code == 0, shown.stderr
    document = _document(shown.stdout)
    assert document["observedPermissions"] == ["ipm.organization.get"]
    assert document["observedGeneration"] == 2
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": [link_document()]})
    listed = runner.invoke(app, [*JSON, "sum", "service", "list"])
    assert [s["service"] for s in _document(listed.stdout)] == ["ipm"]
    api.routes[("GET", "/v1/sum/services")] = Response(200, {"items": []})
    assert _document(runner.invoke(app, [*JSON, "sum", "service", "list"]).stdout) == []


@pytest.mark.usefixtures("default_output_mode")
def test_json_enable_without_wait_prints_the_admitted_link(api: FakeApi) -> None:
    route_admitted(api, "POST")
    result = runner.invoke(app, [*JSON, "sum", "service", "enable", "--service", "ipm"])
    assert result.exit_code == 0, result.stderr
    document = _document(result.stdout)
    assert document["resourceId"] == RID and document["desiredGeneration"] == 2
    assert "operationId" not in document
    assert "sk auth refresh" in result.stderr


@pytest.mark.usefixtures("default_output_mode")
def test_json_enable_with_wait_prints_the_link_and_whether_the_session_was_renewed(
    api: FakeApi, renewals: list[bool]
) -> None:
    route_admitted(api, "POST")
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document())
    result = runner.invoke(app, [*JSON, "sum", "service", "enable", "--service", "ipm", "--wait"])
    assert result.exit_code == 0, result.stderr
    document = _document(result.stdout)
    assert document["resourceId"] == RID and document["sessionRenewed"] is True
    assert "access-1" not in result.stdout and "refresh-1" not in result.stdout


@pytest.mark.usefixtures("default_output_mode")
def test_json_disable_of_a_link_already_off_prints_the_current_link(api: FakeApi) -> None:
    api.routes[("GET", f"/v1/sum/services/{RID}")] = Response(200, link_document("absent"))
    result = runner.invoke(app, [*JSON, "sum", "service", "disable", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout)["resourceId"] == RID
    assert "already disabled" in result.stderr and "already disabled" not in result.stdout
