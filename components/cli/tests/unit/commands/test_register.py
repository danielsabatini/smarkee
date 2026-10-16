"""Comando `sk register`: opções, configuração, validação local e mensagens de saída."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sk.features.core.user import RegistrationAccepted
from sk.http import ApiRejectedError, ApiUnavailableError
from sk.main import app

runner = CliRunner()
REGISTER = ["register", "--name", "Ana", "--surname", "Souza", "--email", "ana@example.com"]


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in (
        "SK_CORE_API_URL",
        "SK_CORE_ALLOW_INSECURE_HTTP",
        "SK_AUTH_ISSUER",
        "SK_AUTH_CLIENT_ID",
    ):
        monkeypatch.delenv(variable, raising=False)


def write_config(tmp_path: Path, content: str) -> None:
    (tmp_path / "sk").mkdir(exist_ok=True)
    (tmp_path / "sk" / "config.toml").write_text(content, encoding="utf-8")


def fake_submit(calls: list[dict[str, Any]], result: object) -> Any:
    def submit(url: str, **kwargs: Any) -> object:
        calls.append({"url": url, **kwargs})
        if isinstance(result, BaseException):
            raise result
        return result

    return submit


def test_there_is_no_password_option() -> None:
    result = runner.invoke(app, [*REGISTER, "--password", "segredo", "--api-url", "https://a.b"])
    assert result.exit_code == 2
    assert "--password" in result.stderr


def test_the_api_url_must_be_configured(tmp_path: Path) -> None:
    result = runner.invoke(app, REGISTER)
    assert result.exit_code == 2
    assert "SK_CORE_API_URL" in result.stderr


def test_the_api_url_comes_from_the_configuration_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, '[core]\napiUrl = "https://api.arquivo"\n')
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("r-1", "o-1")),
    )
    result = runner.invoke(app, REGISTER)
    assert result.exit_code == 0
    assert calls[0]["url"] == "https://api.arquivo"


def test_the_flag_overrides_the_environment_and_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, '[core]\napiUrl = "https://api.arquivo"\n')
    monkeypatch.setenv("SK_CORE_API_URL", "https://api.ambiente")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("r-1", "o-1")),
    )
    result = runner.invoke(app, [*REGISTER, "--api-url", "https://api.flag"])
    assert result.exit_code == 0
    assert calls[0]["url"] == "https://api.flag"


def test_an_invalid_email_never_reaches_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_be_called(*_: object, **__: object) -> None:
        raise AssertionError("a API não deve ser chamada com dados inválidos")

    monkeypatch.setattr("sk.commands.register.submit_registration", must_not_be_called)
    result = runner.invoke(
        app,
        [
            "register",
            "--name",
            "Ana",
            "--surname",
            "Souza",
            "--email",
            "nao-e-email",
            "--api-url",
            "https://api.example",
        ],
    )
    assert result.exit_code == 2
    assert "formato de um e-mail" in result.stderr


def test_success_prints_the_identities_and_the_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("0199-res", "0199-op")),
    )
    result = runner.invoke(app, [*REGISTER, "--api-url", "https://api.example"])
    assert result.exit_code == 0
    assert "0199-res" in result.stdout
    assert "0199-op" in result.stdout
    assert "Cadastro solicitado" in result.stdout
    assert "confirme o e-mail" in result.stdout
    assert calls[0]["given_name"] == "Ana"
    assert calls[0]["family_name"] == "Souza"


def test_rate_limit_tells_how_long_to_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(
            [], ApiRejectedError(429, "x", error_code="RateLimited", retry_after_seconds=30)
        ),
    )
    result = runner.invoke(app, [*REGISTER, "--api-url", "https://api.example"])
    assert result.exit_code == 1
    assert "Aguarde 30 segundos" in result.stderr


def test_a_rejected_field_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(
            [],
            ApiRejectedError(400, "Campo inválido", error_code="ValidationFailed", field="email"),
        ),
    )
    result = runner.invoke(app, [*REGISTER, "--api-url", "https://api.example"])
    assert result.exit_code == 2
    assert "Campo recusado pela API" in result.stderr
    assert "email" in result.stderr


def test_an_unavailable_service_asks_to_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit([], ApiUnavailableError("a API respondeu com HTTP 503")),
    )
    result = runner.invoke(app, [*REGISTER, "--api-url", "https://api.example"])
    assert result.exit_code == 1
    assert "Repita em alguns minutos" in result.stderr


def test_help_is_in_portuguese_and_lists_the_three_fields() -> None:
    result = runner.invoke(app, ["register", "--help"])
    assert result.exit_code == 0
    for option in ("--name", "--surname", "--email", "--api-url"):
        assert option in result.stdout
    assert "--password" not in result.stdout
