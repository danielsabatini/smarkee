"""Comandos `sk ipm organization`: pedidos, espera, mensagens e saídas, contra uma API simulada."""

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
RID = "01a14168-b59d-7475-8db7-c5cf57fa100b"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
PATH = "/v1/ipm/organizations"
ORGANIZATION = f"{PATH}/{RID}"
OPERATION = f"{ORGANIZATION}/operations/{OPID}"


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
    """A espera do `--wait` não dorme nos testes."""

    def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("sk.commands.ipm.time.sleep", no_wait)


def organization_document(
    *, name: str = "acme", phase: str = "Ready", state: str | None = "active", version: str = "3"
) -> dict[str, Any]:
    return {
        "resourceId": RID,
        "resourceVersion": version,
        "desiredGeneration": 1,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "name": name,
            "platformAccess": "granted",
        },
        **(
            {"observed": {"presence": "present", "name": name, "organizationState": state}}
            if state
            else {}
        ),
        "createdAt": "2026-10-16T10:00:00+00:00",
        "updatedAt": "2026-10-16T10:00:05+00:00",
    }


def operation_document(status: str, reason: str | None = None) -> Response:
    document: dict[str, Any] = {"operationId": OPID, "operationStatus": status}
    if reason:
        document["operationStatusReason"] = reason
    return Response(200, document)


def accepted() -> Response:
    return Response(202, {"resourceId": RID, "operationId": OPID})


def body_of(request: urllib.request.Request) -> object:
    return json.loads(cast(bytes, request.data))


def test_create_sends_the_name_with_the_session_token_and_an_idempotency_key(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme"])

    assert result.exit_code == 0, result.stdout
    request = api.requests[-1]
    assert request.get_header("Authorization") == "Bearer access-1"
    assert request.get_header("Idempotency-key")
    assert body_of(request) == {"name": "acme"}
    assert RID in result.stdout and OPID in result.stdout
    assert "sk ipm organization get --resource-id" in " ".join(result.stdout.split())


def test_create_requires_the_name_and_a_valid_one_before_any_call(api: FakeApi) -> None:
    missing = runner.invoke(app, ["ipm", "organization", "create"])
    assert missing.exit_code == 2
    assert "--name" in missing.stderr

    for invalid in ("Acme", "-acme", "acme-", "a" * 64, "com espaço"):
        result = runner.invoke(app, ["ipm", "organization", "create", "--name", invalid])
        assert result.exit_code == 2, invalid
        assert "Value not accepted" in result.stderr
        assert invalid not in result.stderr  # a mensagem não repete o valor informado
    assert api.requests == []


def test_create_wait_waits_for_ready_and_shows_the_organization(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation_document("in_progress"),
        operation_document("completed"),
    ]
    api.routes[("GET", ORGANIZATION)] = [
        Response(200, organization_document(phase="Reconciling", state=None)),
        Response(200, organization_document()),
    ]

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Organization created" in result.stdout
    assert "Ready" in result.stdout and "active" in result.stdout


def test_create_wait_does_not_stop_on_the_old_name_after_a_rename_is_pending(
    api: FakeApi,
) -> None:
    """A espera confere o nome pedido: `Ready` com outro nome ainda não é o resultado."""
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("completed")
    api.routes[("GET", ORGANIZATION)] = [
        Response(200, organization_document(name="antigo")),
        Response(200, organization_document(name="acme")),
    ]

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert [request.get_method() for request in api.requests].count("GET") == 4


def test_wait_stops_with_the_reason_when_the_operation_is_rejected(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("rejected", "validation")
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document(phase="Pending"))

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme", "--wait"])

    assert result.exit_code == 1
    assert "Request not completed" in result.stderr and "validation" in result.stderr
    assert "reserved or already in use" in " ".join(result.stderr.split())


def test_wait_times_out_with_a_hint(api: FakeApi, monkeypatch: pytest.MonkeyPatch) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("in_progress")
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document(phase="Reconciling"))
    clock = iter(range(0, 1000, 20))  # cada leitura do relógio avança 20 s
    monkeypatch.setattr("sk.commands.ipm.time.monotonic", lambda: next(clock))

    result = runner.invoke(
        app, ["ipm", "organization", "create", "--name", "acme", "--wait", "--timeout", "30"]
    )

    assert result.exit_code == 1
    assert "Timed out" in result.stderr and "Reconciling" in result.stderr
    assert f"sk ipm organization get --resource-id {RID}" in " ".join(result.stderr.split())


def test_wait_asks_for_a_fresh_token_on_every_poll(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation_document("in_progress"),
        operation_document("completed"),
    ]
    api.routes[("GET", ORGANIZATION)] = [
        Response(200, organization_document(phase="Reconciling")),
        Response(200, organization_document()),
    ]
    asked: list[bool] = []

    def counting_token(*_: object, **__: object) -> str:
        asked.append(True)
        return "access-1"

    monkeypatch.setattr("sk.commands.shared.current_access_token", counting_token)

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(asked) >= 3  # o pedido de criar e uma vez por leitura (2)


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        (403, "EmailNotVerified", "Verify your e-mail first"),
        (403, "QuotaExceeded", "Organization limit"),
        (403, "Forbidden", "sk sum service enable --service ipm --wait"),
        (401, "Unauthorized", "sk auth login"),
        (503, "Unavailable", "Try again"),
    ],
)
def test_create_translates_the_api_refusals_into_hints(
    api: FakeApi, status: int, error_code: str, expected: str
) -> None:
    api.routes[("POST", PATH)] = http_error(status, error_code, "recusado")

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme"])

    assert result.exit_code == 1
    assert expected in " ".join(result.stderr.split())


def test_get_shows_the_organization_and_the_operation(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document())
    api.routes[("GET", OPERATION)] = operation_document("completed")

    result = runner.invoke(
        app,
        ["ipm", "organization", "get", "--resource-id", RID, "--operation-id", OPID],
    )

    assert result.exit_code == 0, result.stderr
    for text in ("acme", "active", "Ready", "granted", "completed"):
        assert text in result.stdout


def test_get_of_an_unknown_organization_is_not_found(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = http_error(404, "NotFound", "Recurso não encontrado.")

    result = runner.invoke(app, ["ipm", "organization", "get", "--resource-id", RID])

    assert result.exit_code == 1
    assert "Organization not found" in " ".join(result.stderr.split())


def test_get_rejects_an_identifier_outside_the_contract_before_any_call(api: FakeApi) -> None:
    result = runner.invoke(app, ["ipm", "organization", "get", "--resource-id", "../x?y"])

    assert result.exit_code == 2
    assert api.requests == []


def test_list_shows_a_table_and_follows_the_cursor(api: FakeApi) -> None:
    first = {"items": [organization_document(name="uma")], "nextCursor": "abc"}
    second = {"items": [organization_document(name="duas", phase="Reconciling", state=None)]}
    api.routes[("GET", PATH)] = [Response(200, first), Response(200, second)]

    result = runner.invoke(app, ["ipm", "organization", "list"])

    assert result.exit_code == 0, result.stderr
    assert "uma" in result.stdout and "duas" in result.stdout and "unknown" in result.stdout
    assert "cursor=abc" in api.requests[-1].full_url


def test_list_without_organizations_says_so(api: FakeApi) -> None:
    api.routes[("GET", PATH)] = Response(200, {"items": []})

    result = runner.invoke(app, ["ipm", "organization", "list"])

    assert result.exit_code == 0
    assert "No Organizations" in result.stdout


def test_update_reads_the_current_version_before_renaming(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document(version="7"))
    api.routes[("PATCH", ORGANIZATION)] = accepted()

    result = runner.invoke(
        app, ["ipm", "organization", "update", "--resource-id", RID, "--name", "novo"]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    patch = next(request for request in api.requests if request.get_method() == "PATCH")
    assert body_of(patch) == {"resourceVersion": "7", "name": "novo"}
    assert patch.get_header("Idempotency-key")


def test_update_to_the_same_name_does_nothing(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document(name="acme"))

    result = runner.invoke(
        app, ["ipm", "organization", "update", "--resource-id", RID, "--name", "acme"]
    )

    assert result.exit_code == 0
    assert "Nothing to do" in result.stdout
    assert [request.get_method() for request in api.requests] == ["GET"]


def test_update_wait_waits_for_the_new_name(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = [
        Response(200, organization_document(name="antigo")),  # leitura antes do pedido
        Response(200, organization_document(name="antigo")),  # ainda o nome antigo
        Response(200, organization_document(name="novo")),
    ]
    api.routes[("PATCH", ORGANIZATION)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("completed")

    result = runner.invoke(
        app,
        ["ipm", "organization", "update", "--resource-id", RID, "--name", "novo", "--wait"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Organization renamed" in result.stdout and "novo" in result.stdout


def test_update_conflict_tells_to_inspect_again(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document(name="antigo"))
    api.routes[("PATCH", ORGANIZATION)] = http_error(409, "Conflict", "mudou")

    result = runner.invoke(
        app, ["ipm", "organization", "update", "--resource-id", RID, "--name", "novo"]
    )

    assert result.exit_code == 1
    assert "changed since it was last read" in " ".join(result.stderr.split())


def test_delete_reads_the_current_version_and_sends_it(api: FakeApi) -> None:
    api.routes[("GET", ORGANIZATION)] = Response(200, organization_document(version="9"))
    api.routes[("DELETE", ORGANIZATION)] = accepted()

    result = runner.invoke(app, ["ipm", "organization", "delete", "--resource-id", RID])

    assert result.exit_code == 0, result.stdout + result.stderr
    delete = next(request for request in api.requests if request.get_method() == "DELETE")
    assert "resourceVersion=9" in delete.full_url
    assert delete.get_header("Idempotency-key")


def test_delete_wait_ends_when_the_organization_is_gone(api: FakeApi) -> None:
    api.routes[("DELETE", ORGANIZATION)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation_document("in_progress"),
        operation_document("completed"),
    ]
    # Antes do pedido a Organization existe; depois, ainda `Deleting`; por fim, a linha some (404).
    api.routes[("GET", ORGANIZATION)] = [
        Response(200, organization_document()),
        Response(200, organization_document(phase="Deleting")),
        http_error(404, "NotFound", "Recurso não encontrado."),
    ]

    result = runner.invoke(app, ["ipm", "organization", "delete", "--resource-id", RID, "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Organization deleted" in result.stdout and "removed" in result.stdout


def test_wait_keeps_polling_while_the_manager_has_not_recorded_the_request_yet(
    api: FakeApi,
) -> None:
    """Logo depois do `202`, a leitura dá `404` até o Manager gravar (LOOP §6.1.1): é espera."""
    api.routes[("POST", PATH)] = accepted()
    not_yet = http_error(404, "NotFound", "Recurso não encontrado.")
    api.routes[("GET", OPERATION)] = [not_yet, not_yet, operation_document("completed")]
    api.routes[("GET", ORGANIZATION)] = [not_yet, not_yet, Response(200, organization_document())]

    result = runner.invoke(app, ["ipm", "organization", "create", "--name", "acme", "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Organization created" in result.stdout


def test_wait_times_out_when_the_request_never_becomes_visible(
    api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = http_error(404, "NotFound", "Recurso não encontrado.")
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr("sk.commands.ipm.time.monotonic", lambda: next(clock))

    result = runner.invoke(
        app, ["ipm", "organization", "create", "--name", "acme", "--wait", "--timeout", "30"]
    )

    assert result.exit_code == 1
    assert "Timed out" in result.stderr and "not visible yet" in result.stderr
