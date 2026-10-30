"""Comando `sk account status`: consulta de status por ticket temporário e reenvio de ativação."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sk import output
from sk.features.core.account import RegistrationStatus
from sk.http import ApiRejectedError
from sk.main import app

runner = CliRunner()
STATUS_TICKET = ["account", "status", "--ticket", "0192d4f8-7b4a-7123-89ab-cdef01234567"]


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("SK_API_URL", "https://api.example")
    for variable in (
        "SK_API_ALLOW_INSECURE_HTTP",
        "SK_AUTH_ISSUER",
        "SK_AUTH_CLIENT_ID",
    ):
        monkeypatch.delenv(variable, raising=False)


def test_status_requires_ticket() -> None:
    result = runner.invoke(app, ["account", "status"])
    assert result.exit_code == 2
    assert "Provide --ticket" in result.stderr


def test_status_query_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_status(
        url: str, *, ticket: str, allow_insecure_http: bool
    ) -> RegistrationStatus:
        return RegistrationStatus(
            phase="Reconciling",
            email_masked="a***a@example.com",
            email_dispatched=False,
            activated=False,
            ticket_expires_at="2026-10-30T15:30:00Z",
        )

    monkeypatch.setattr("sk.commands.account.get_registration_status", fake_status)
    result = runner.invoke(app, STATUS_TICKET)
    assert result.exit_code == 0, result.stderr
    assert "Registration status" in result.stdout
    assert "0192d4f8-7b4a-7123-89ab-cdef01234567" in result.stdout
    assert "Reconciling" in result.stdout
    assert "a***a@example.com" in result.stdout


def test_status_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    output.configure(raw=False)

    def fake_status(
        url: str, *, ticket: str, allow_insecure_http: bool
    ) -> RegistrationStatus:
        return RegistrationStatus(
            phase="Ready",
            email_masked="a***a@example.com",
            email_dispatched=True,
            activated=True,
            ticket_expires_at="2026-10-30T15:30:00Z",
        )

    monkeypatch.setattr("sk.commands.account.get_registration_status", fake_status)
    result = runner.invoke(app, ["--output", "json", *STATUS_TICKET])
    output.configure(raw=False)
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["phase"] == "Ready"
    assert data["activated"] is True
    assert data["emailDispatched"] is True
    assert data["emailMasked"] == "a***a@example.com"


def test_status_ticket_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_status(*_: Any, **__: Any) -> None:
        raise ApiRejectedError(404, "Ticket not found", error_code="TicketNotFound")

    monkeypatch.setattr("sk.commands.account.get_registration_status", fake_status)
    result = runner.invoke(app, STATUS_TICKET)
    assert result.exit_code == 1
    assert "Ticket not found" in result.stderr


def test_status_resend_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_resend(url: str, *, ticket: str, allow_insecure_http: bool) -> None:
        calls.append(ticket)

    monkeypatch.setattr("sk.commands.account.resend_registration", fake_resend)
    result = runner.invoke(app, [*STATUS_TICKET, "--resend"])
    assert result.exit_code == 0, result.stderr
    assert calls == ["0192d4f8-7b4a-7123-89ab-cdef01234567"]
    assert "Activation email resent" in result.stdout


def test_status_resend_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resend(*_: Any, **__: Any) -> None:
        raise ApiRejectedError(
            429,
            "Too many requests",
            error_code="RateLimited",
            retry_after_seconds=45,
        )

    monkeypatch.setattr("sk.commands.account.resend_registration", fake_resend)
    result = runner.invoke(app, [*STATUS_TICKET, "--resend"])
    assert result.exit_code == 1
    assert "Too many requests" in result.stderr
    assert "Wait 45 seconds and repeat" in result.stderr


def test_status_wait_converges_when_email_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    def fake_status(url: str, *, ticket: str, allow_insecure_http: bool) -> RegistrationStatus:
        nonlocal call_count
        call_count += 1
        return RegistrationStatus(
            phase="Pending" if call_count == 1 else "Ready",
            email_masked="a***a@example.com",
            email_dispatched=call_count > 1,
            activated=False,
            ticket_expires_at="2026-10-30T15:30:00Z",
        )

    monkeypatch.setattr("sk.commands.account.get_registration_status", fake_status)
    result = runner.invoke(app, [*STATUS_TICKET, "--wait"])
    assert result.exit_code == 0, result.stderr
    assert "Registration status" in result.stdout
    assert "Ready" in result.stdout
