"""Comandos `sk ipm serviceaccount`: pedidos, espera e saídas, contra uma API simulada."""

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
ORG = "01a15e61-6d1e-7096-878a-d5f450b858f1"
RID = "01a15e61-6d1e-7096-878a-d5f450b858f2"
PATH = "/v1/ipm/serviceaccounts"
SERVICEACCOUNT = f"{PATH}/{RID}"


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


def sa_document(
    *,
    phase: str = "Ready",
    name: str = "ci-deployer",
    description: str = "CI agent",
    roles: list[str] | None = None,
    protected: bool = True,
    version: str = "1",
    desired_generation: int = 1,
    observed_generation: int | None = 1,
    conditions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    roles = roles or ["ipm.serviceaccountViewer"]
    return {
        "resourceId": RID,
        "resourceVersion": version,
        "desiredGeneration": desired_generation,
        **({"observedGeneration": observed_generation} if observed_generation is not None else {}),
        "phase": phase,
        "conditions": conditions or [],
        "desired": {
            "lifecycle": "active",
            "organizationId": ORG,
            "name": name,
            "description": description,
            "roles": roles,
            "permissions": ["ipm.serviceaccount.get"],
            "deletionProtection": protected,
            "keys": [
                {
                    "publicKey": "-----BEGIN PUBLIC KEY-----\n...",
                    "expiresAt": "2027-01-01T00:00:00Z",
                    "fingerprint": "abc12345",
                }
            ],
        },
        "observed": {
            "keys": [
                {
                    "keyId": "k-001",
                    "fingerprint": "abc12345",
                    "expiresAt": "2027-01-01T00:00:00Z",
                    "status": "active",
                }
            ]
        },
    }


def test_create_serviceaccount_generates_key_and_requests_creation(
    api: FakeApi, tmp_path: Path
) -> None:
    api.routes[("POST", PATH)] = Response(
        201, sa_document(phase="Pending", observed_generation=None)
    )
    key_file = tmp_path / "sa.json"
    result = runner.invoke(
        app,
        [
            "ipm",
            "serviceaccount",
            "create",
            "--name",
            "ci-deployer",
            "--organization-id",
            ORG,
            "--key-file",
            str(key_file),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "Creation requested" in result.stdout
    assert key_file.exists()


def test_get_serviceaccount(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = Response(200, sa_document())
    result = runner.invoke(app, ["ipm", "serviceaccount", "get", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert "ci-deployer" in result.stdout
    assert "Service Account" in result.stdout


def test_list_serviceaccounts(api: FakeApi) -> None:
    api.routes[("GET", PATH)] = Response(200, {"items": [sa_document()], "nextCursor": None})
    result = runner.invoke(app, ["ipm", "serviceaccount", "list", "--organization-id", ORG])
    assert result.exit_code == 0, result.stderr
    assert "ci-deployer" in result.stdout


def test_protect_and_unprotect_serviceaccount(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = Response(200, sa_document(protected=True))
    api.routes[("PATCH", SERVICEACCOUNT)] = Response(
        200, sa_document(phase="Reconciling", desired_generation=2, version="2")
    )
    result = runner.invoke(app, ["ipm", "serviceaccount", "unprotect", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert "Update requested" in result.stdout


def test_delete_serviceaccount(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = Response(200, sa_document(protected=False))
    api.routes[("DELETE", SERVICEACCOUNT)] = Response(202, sa_document(phase="Deleting"))
    result = runner.invoke(app, ["ipm", "serviceaccount", "delete", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert "Deletion requested" in result.stdout


def test_key_list_serviceaccount(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = Response(200, sa_document())
    result = runner.invoke(app, ["ipm", "serviceaccount", "key", "list", "--resource-id", RID])
    assert result.exit_code == 0, result.stderr
    assert "k-001" in result.stdout


def test_key_remove_refuses_the_last_key(
    api: FakeApi,
) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = Response(
        200,
        {
            **sa_document(),
            "desired": {
                **sa_document()["desired"],
                "keys": [
                    {
                        "publicKey": "PK",
                        "expiresAt": "2027-01-01T00:00:00Z",
                        "fingerprint": "f" * 64,
                    }
                ],
            },
        },
    )
    result = runner.invoke(
        app, ["ipm", "serviceaccount", "key", "remove", "--resource-id", RID, "--key-id", "k-001"]
    )
    assert result.exit_code == 2
    assert "at least one key" in result.stderr
    assert not [r for r in api.requests if r.get_method() == "PATCH"]


def test_key_add_sends_only_publickey_and_expiresat(api: FakeApi, tmp_path: Path) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = Response(
        200,
        {
            **sa_document(),
            "desired": {
                **sa_document()["desired"],
                "keys": [
                    {
                        "publicKey": "PK",
                        "expiresAt": "2027-01-01T00:00:00Z",
                        "fingerprint": "f" * 64,
                    }
                ],
            },
        },
    )
    api.routes[("PATCH", SERVICEACCOUNT)] = Response(
        200, sa_document(phase="Reconciling", desired_generation=2, version="2")
    )
    result = runner.invoke(
        app,
        [
            "ipm",
            "serviceaccount",
            "key",
            "add",
            "--resource-id",
            RID,
            "--key-file",
            str(tmp_path / "k.json"),
        ],
    )
    assert result.exit_code == 0, result.stderr
    patch = next(r for r in api.requests if r.get_method() == "PATCH")
    keys = json.loads(cast("bytes", patch.data))["keys"]
    assert len(keys) == 2
    assert all(set(k) == {"publicKey", "expiresAt"} for k in keys)


def test_key_file_missing_file_explains_the_path_without_raw_errno(tmp_path: Path) -> None:
    missing = tmp_path / "nao-existe.json"
    result = runner.invoke(
        app,
        ["ipm", "serviceaccount", "key-file", "--resource-id", RID, "--key-file", str(missing)],
    )
    assert result.exit_code == 2
    assert "Could not read the key file" in result.output
    assert "nao-existe.json" in result.output
    assert "Errno" not in result.output


def test_create_reads_the_public_key_from_stdin(
    api: FakeApi, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sk.identity.keys import generate_key_pair

    monkeypatch.chdir(tmp_path)
    keypair = generate_key_pair()
    api.routes[("POST", PATH)] = Response(
        201, sa_document(phase="Pending", observed_generation=None)
    )
    result = runner.invoke(
        app,
        [
            *["ipm", "serviceaccount", "create", "--name", "ci", "--organization-id", ORG],
            *["--public-key-file", "-"],
        ],
        input=keypair.public_pem,
    )
    assert result.exit_code == 0, result.output
    assert list(tmp_path.glob("*.json")) == []  # com a pública dada, nenhum arquivo de chave nasce


def test_create_with_wait_waits_for_the_admitted_generation_to_be_observed(
    api: FakeApi, tmp_path: Path
) -> None:
    api.routes[("POST", PATH)] = Response(
        201, sa_document(phase="Pending", observed_generation=None)
    )
    api.routes[("GET", SERVICEACCOUNT)] = [
        Response(200, sa_document(phase="Pending", observed_generation=None)),
        Response(200, sa_document(phase="Reconciling", observed_generation=None)),
        Response(200, sa_document(phase="Ready", observed_generation=1)),
    ]
    result = runner.invoke(
        app,
        [
            *["ipm", "serviceaccount", "create", "--name", "ci-deployer", "--wait"],
            *["--organization-id", ORG, "--key-file", str(tmp_path / "sa.json")],
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "Service account created" in result.stdout
    assert [r.get_method() for r in api.requests].count("GET") == 3
    assert not [r for r in api.requests if "operations" in r.full_url]


def test_update_waits_for_the_new_generation_not_a_stale_ready(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = [
        Response(200, sa_document(protected=True)),  # leitura que escolhe a versão
        Response(200, sa_document(phase="Ready", desired_generation=2, observed_generation=1)),
        Response(200, sa_document(phase="Ready", desired_generation=2, observed_generation=2)),
    ]
    api.routes[("PATCH", SERVICEACCOUNT)] = Response(
        200, sa_document(phase="Reconciling", desired_generation=2, version="2")
    )
    result = runner.invoke(
        app, ["ipm", "serviceaccount", "unprotect", "--resource-id", RID, "--wait"]
    )
    assert result.exit_code == 0, result.stderr
    assert [r.get_method() for r in api.requests].count("GET") == 3


def test_a_failed_phase_with_the_generation_observed_is_a_failure(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = [
        Response(200, sa_document(protected=True)),
        Response(
            200,
            sa_document(
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
    api.routes[("PATCH", SERVICEACCOUNT)] = Response(
        200, sa_document(phase="Reconciling", desired_generation=2, version="2")
    )
    result = runner.invoke(
        app, ["ipm", "serviceaccount", "unprotect", "--resource-id", RID, "--wait"]
    )
    assert result.exit_code == 1
    assert "ProviderRejected" in result.stderr


def test_delete_with_wait_finishes_when_the_resource_is_gone(api: FakeApi) -> None:
    api.routes[("GET", SERVICEACCOUNT)] = [
        Response(200, sa_document(protected=False)),
        Response(200, sa_document(phase="Deleting", desired_generation=2, observed_generation=1)),
        http_error(404, "NotFound", "não encontrada"),
    ]
    api.routes[("DELETE", SERVICEACCOUNT)] = Response(
        202, sa_document(phase="Deleting", desired_generation=2)
    )
    result = runner.invoke(app, ["ipm", "serviceaccount", "delete", "--resource-id", RID, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert "removed" in result.stdout


def test_name_in_use_is_explained(api: FakeApi, tmp_path: Path) -> None:
    api.routes[("POST", PATH)] = http_error(409, "NameInUse", "nome em uso", "name")
    result = runner.invoke(
        app,
        [
            *["ipm", "serviceaccount", "create", "--name", "ci-deployer"],
            *["--organization-id", ORG, "--key-file", str(tmp_path / "sa.json")],
        ],
    )
    assert result.exit_code == 1
    assert "name already exists" in result.stderr
