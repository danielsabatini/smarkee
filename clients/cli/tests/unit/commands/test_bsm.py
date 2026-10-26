"""Comandos `sk bsm account`: pedidos, espera, mensagens e saídas, contra uma API simulada."""

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
RID = "01a14168-b59d-7475-8db7-c5cf57fa100b"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"
PATH = "/v1/bsm/accounts"
ACCOUNT = f"{PATH}/{RID}"
OPERATION = f"{ACCOUNT}/operations/{OPID}"


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
    monkeypatch.delenv("SK_BSM_ACCOUNT_ID", raising=False)
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

    monkeypatch.setattr("sk.commands.shared.time.sleep", no_wait)


def account_document(
    *,
    display_name: str = "Acme Cloud Production",
    billing_currency: str = "BRL",
    billing_contacts: list[str] | None = None,
    phase: str = "Ready",
    presence: str | None = "present",
    version: str = "3",
    protected: bool = True,
) -> dict[str, Any]:
    contacts = billing_contacts if billing_contacts is not None else ["finops@acme.com"]
    return {
        "resourceId": RID,
        "resourceVersion": version,
        "desiredGeneration": 1,
        "phase": phase,
        "conditions": [],
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "displayName": display_name,
            "billingCurrency": billing_currency,
            "billingContacts": contacts,
            "deletionProtection": protected,
        },
        **(
            {
                "observed": {
                    "presence": presence,
                    "displayName": display_name,
                    "billingCurrency": billing_currency,
                    "billingContacts": contacts,
                }
            }
            if presence
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


def test_create_sends_fields_with_session_token_and_idempotency_key(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme Cloud Production",
            "--currency",
            "BRL",
            "--contact",
            "finops@acme.com",
        ],
    )

    assert result.exit_code == 0, result.stdout
    request = api.requests[-1]
    assert request.get_header("Authorization") == "Bearer access-1"
    assert request.get_header("Idempotency-key")
    assert body_of(request) == {
        "displayName": "Acme Cloud Production",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.com"],
    }
    assert RID in result.stdout and OPID in result.stdout
    assert "sk bsm account get --resource-id" in " ".join(result.stdout.split())


def test_create_requires_valid_options_before_any_call(api: FakeApi) -> None:
    missing = runner.invoke(app, ["bsm", "account", "create"])
    assert missing.exit_code == 2
    assert "--display-name" in missing.stderr

    bad_currency = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme",
            "--currency",
            "GBP",
            "--contact",
            "finops@acme.com",
        ],
    )
    assert bad_currency.exit_code == 2
    assert "Value not accepted" in bad_currency.stderr

    bad_contact = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme",
            "--currency",
            "BRL",
            "--contact",
            "not-an-email",
        ],
    )
    assert bad_contact.exit_code == 2
    assert "Value not accepted" in bad_contact.stderr
    assert api.requests == []


def test_create_wait_waits_for_ready_and_shows_the_account(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation_document("in_progress"),
        operation_document("completed"),
    ]
    api.routes[("GET", ACCOUNT)] = [
        Response(200, account_document(phase="Reconciling", presence=None)),
        Response(200, account_document()),
    ]

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme Cloud Production",
            "--currency",
            "BRL",
            "--contact",
            "finops@acme.com",
            "--wait",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Billing Account created" in result.stdout
    assert "Ready" in result.stdout and "present" in result.stdout


def test_wait_stops_with_the_reason_when_the_operation_is_rejected(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("rejected", "validation")
    api.routes[("GET", ACCOUNT)] = Response(200, account_document(phase="Pending"))

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme Cloud Production",
            "--currency",
            "BRL",
            "--contact",
            "finops@acme.com",
            "--wait",
        ],
    )

    assert result.exit_code == 1
    assert "Request not completed" in result.stderr and "validation" in result.stderr
    assert "already in use" in " ".join(result.stderr.split())


def test_wait_times_out_with_a_hint(api: FakeApi, monkeypatch: pytest.MonkeyPatch) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("in_progress")
    api.routes[("GET", ACCOUNT)] = Response(200, account_document(phase="Reconciling"))
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr("sk.commands.shared.time.monotonic", lambda: next(clock))

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme Cloud Production",
            "--currency",
            "BRL",
            "--contact",
            "finops@acme.com",
            "--wait",
            "--timeout",
            "30",
        ],
    )

    assert result.exit_code == 1
    assert "Timed out" in result.stderr and "Reconciling" in result.stderr
    assert "sk bsm account get" in result.stderr
    assert RID in result.stderr


@pytest.mark.parametrize(
    ("status", "error_code", "expected"),
    [
        (403, "EmailNotVerified", "e-mail is not verified"),
        (403, "QuotaExceeded", "Billing Account limit"),
        (403, "Forbidden", "bsm.account.*"),
        (401, "Unauthorized", "sk auth login"),
        (503, "Unavailable", "Try again"),
    ],
)
def test_create_translates_the_api_refusals_into_hints(
    api: FakeApi, status: int, error_code: str, expected: str
) -> None:
    api.routes[("POST", PATH)] = http_error(status, error_code, "recusado")

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme Cloud Production",
            "--currency",
            "BRL",
            "--contact",
            "finops@acme.com",
        ],
    )

    assert result.exit_code == 1
    assert expected in " ".join(result.stderr.split())


def test_get_shows_the_account_and_the_operation(api: FakeApi) -> None:
    api.routes[("GET", ACCOUNT)] = Response(200, account_document())
    api.routes[("GET", OPERATION)] = operation_document("completed")

    result = runner.invoke(
        app,
        ["bsm", "account", "get", "--resource-id", RID, "--operation-id", OPID],
    )

    assert result.exit_code == 0, result.stderr
    for text in (
        "Acme Cloud Production",
        "BRL",
        "finops@acme.com",
        "present",
        "Ready",
        "completed",
    ):
        assert text in result.stdout


def test_get_of_an_unknown_account_is_not_found(api: FakeApi) -> None:
    api.routes[("GET", ACCOUNT)] = http_error(404, "NotFound", "Recurso não encontrado.")

    result = runner.invoke(app, ["bsm", "account", "get", "--resource-id", RID])

    assert result.exit_code == 1
    assert "Billing Account not found" in " ".join(result.stderr.split())


def test_list_shows_a_table_and_follows_the_cursor(api: FakeApi) -> None:
    first = {"items": [account_document(display_name="uma")], "nextCursor": "abc"}
    second = {"items": [account_document(display_name="duas", phase="Reconciling", presence=None)]}
    api.routes[("GET", PATH)] = [Response(200, first), Response(200, second)]

    result = runner.invoke(app, ["bsm", "account", "list"])

    assert result.exit_code == 0, result.stderr
    assert "uma" in result.stdout and "duas" in result.stdout and "unknown" in result.stdout
    assert "cursor=abc" in api.requests[-1].full_url


def test_list_without_accounts_says_so(api: FakeApi) -> None:
    api.routes[("GET", PATH)] = Response(200, {"items": []})

    result = runner.invoke(app, ["bsm", "account", "list"])

    assert result.exit_code == 0
    assert "No Billing Accounts" in result.stdout


def test_update_reads_the_current_version_before_patching(api: FakeApi) -> None:
    api.routes[("GET", ACCOUNT)] = Response(200, account_document(version="7"))
    api.routes[("PATCH", ACCOUNT)] = accepted()

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "update",
            "--resource-id",
            RID,
            "--display-name",
            "Novo Nome",
            "--contact",
            "novo@acme.com",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    patch = next(request for request in api.requests if request.get_method() == "PATCH")
    assert body_of(patch) == {
        "resourceVersion": "7",
        "displayName": "Novo Nome",
        "billingContacts": ["novo@acme.com"],
    }
    assert patch.get_header("Idempotency-key")


def test_update_without_options_is_a_usage_error(api: FakeApi) -> None:
    result = runner.invoke(app, ["bsm", "account", "update", "--resource-id", RID])
    assert result.exit_code == 2
    assert "--display-name" in result.stderr
    assert api.requests == []


def test_update_to_the_same_values_does_nothing(api: FakeApi) -> None:
    api.routes[("GET", ACCOUNT)] = Response(200, account_document(display_name="Acme"))

    result = runner.invoke(
        app, ["bsm", "account", "update", "--resource-id", RID, "--display-name", "Acme"]
    )

    assert result.exit_code == 0
    assert "Nothing to do" in result.stdout
    assert [request.get_method() for request in api.requests] == ["GET"]


def test_unprotect_and_protect_commands(api: FakeApi) -> None:
    api.routes[("GET", ACCOUNT)] = Response(200, account_document(version="9", protected=True))
    api.routes[("PATCH", ACCOUNT)] = accepted()

    already = runner.invoke(app, ["bsm", "account", "protect", "--resource-id", RID])
    assert already.exit_code == 0
    assert "already protected" in " ".join(already.stdout.split())

    result = runner.invoke(app, ["bsm", "account", "unprotect", "--resource-id", RID])
    assert result.exit_code == 0, result.stdout + result.stderr
    patch = next(request for request in api.requests if request.get_method() == "PATCH")
    assert body_of(patch) == {"resourceVersion": "9", "deletionProtection": False}


def test_delete_wait_ends_when_the_account_is_gone(api: FakeApi) -> None:
    api.routes[("DELETE", ACCOUNT)] = accepted()
    api.routes[("GET", OPERATION)] = [
        operation_document("in_progress"),
        operation_document("completed"),
    ]
    api.routes[("GET", ACCOUNT)] = [
        Response(200, account_document()),
        Response(200, account_document(phase="Deleting")),
        http_error(404, "NotFound", "Recurso não encontrado."),
    ]

    result = runner.invoke(app, ["bsm", "account", "delete", "--resource-id", RID, "--wait"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Billing Account deleted" in result.stdout and "removed" in result.stdout


def test_active_account_configuration_and_save_on_create_wait(api: FakeApi, tmp_path: Path) -> None:
    api.routes[("POST", PATH)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("completed")
    api.routes[("GET", ACCOUNT)] = Response(200, account_document())

    result = runner.invoke(
        app,
        [
            "bsm",
            "account",
            "create",
            "--display-name",
            "Acme Cloud Production",
            "--currency",
            "BRL",
            "--contact",
            "finops@acme.com",
            "--wait",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Saved as the active Billing Account" in result.stdout
    text = (tmp_path / "sk" / "config.toml").read_text(encoding="utf-8")
    assert f'accountId = "{RID}"' in text

    get_result = runner.invoke(app, ["bsm", "account", "get"])
    assert get_result.exit_code == 0, get_result.stderr


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
    api.routes[("GET", ACCOUNT)] = Response(200, account_document())
    shown = runner.invoke(app, [*JSON, "bsm", "account", "get", "--resource-id", RID])
    assert shown.exit_code == 0, shown.stderr
    document = _document(shown.stdout)
    assert document["billingContacts"] == ["finops@acme.com"]
    assert document["deletionProtection"] is True
    api.routes[("GET", PATH)] = Response(200, {"items": [account_document()]})
    listed = runner.invoke(app, [*JSON, "bsm", "account", "list"])
    assert [a["resourceId"] for a in _document(listed.stdout)] == [RID]
    api.routes[("GET", PATH)] = Response(200, {"items": []})
    assert _document(runner.invoke(app, [*JSON, "bsm", "account", "list"]).stdout) == []


@pytest.mark.usefixtures("default_output_mode")
def test_json_create_without_wait_prints_only_the_acceptance(api: FakeApi) -> None:
    api.routes[("POST", PATH)] = accepted()
    result = runner.invoke(
        app,
        [
            *JSON,
            *["bsm", "account", "create", "--display-name", "Acme", "--currency", "BRL"],
            *["--contact", "finops@acme.com"],
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout) == {"resourceId": RID, "operationId": OPID}


@pytest.mark.usefixtures("default_output_mode")
def test_json_delete_with_wait_prints_the_removed_state(api: FakeApi) -> None:
    api.routes[("DELETE", ACCOUNT)] = accepted()
    api.routes[("GET", OPERATION)] = operation_document("completed")
    api.routes[("GET", ACCOUNT)] = [
        Response(200, account_document()),
        http_error(404, "NotFound", "Recurso não encontrado."),
    ]
    result = runner.invoke(app, [*JSON, "bsm", "account", "delete", "--resource-id", RID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert _document(result.stdout) == {"resourceId": RID, "state": "removed"}


@pytest.mark.usefixtures("default_output_mode")
def test_json_nothing_to_do_prints_the_current_account(api: FakeApi) -> None:
    api.routes[("GET", ACCOUNT)] = Response(200, account_document(display_name="Acme"))
    same = runner.invoke(
        app,
        [*JSON, "bsm", "account", "update", "--resource-id", RID, "--display-name", "Acme"],
    )
    assert same.exit_code == 0, same.stderr
    assert _document(same.stdout)["displayName"] == "Acme"
    assert "Nothing to do" in same.stderr and "Nothing to do" not in same.stdout
    protected = runner.invoke(app, [*JSON, "bsm", "account", "protect", "--resource-id", RID])
    assert _document(protected.stdout)["resourceId"] == RID
    assert all(request.get_method() == "GET" for request in api.requests)
