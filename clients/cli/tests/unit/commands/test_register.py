"""Comando `sk register`: opções, configuração, validação local e mensagens de saída."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sk.defaults import PRD_API_URL
from sk.features.core.account import RegistrationAccepted
from sk.http import ApiRejectedError, ApiUnavailableError
from sk.main import app

runner = CliRunner()
REGISTER = ["register", "--name", "Ana", "--surname", "Souza", "--email", "ana@example.com"]


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in (
        "SK_API_URL",
        "SK_API_ALLOW_INSECURE_HTTP",
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
    result = runner.invoke(app, [*REGISTER, "--password", "segredo"])
    assert result.exit_code == 2
    assert "--password" in result.stderr


def test_without_any_configuration_the_production_api_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("r-1", "o-1")),
    )
    result = runner.invoke(app, REGISTER)
    assert result.exit_code == 0, result.stderr
    assert calls[0]["url"] == PRD_API_URL


def test_the_api_url_comes_from_the_configuration_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, '[api]\nurl = "https://api.arquivo"\n')
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("r-1", "o-1")),
    )
    result = runner.invoke(app, REGISTER)
    assert result.exit_code == 0
    assert calls[0]["url"] == "https://api.arquivo"


def test_the_environment_overrides_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(tmp_path, '[api]\nurl = "https://api.arquivo"\n')
    monkeypatch.setenv("SK_API_URL", "https://api.ambiente")
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("r-1", "o-1")),
    )
    result = runner.invoke(app, REGISTER)
    assert result.exit_code == 0
    assert calls[0]["url"] == "https://api.ambiente"


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
        ],
    )
    assert result.exit_code == 2
    assert "format of an e-mail" in result.stderr


def test_success_prints_the_identities_and_the_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(calls, RegistrationAccepted("0199-res", "0199-op")),
    )
    result = runner.invoke(app, REGISTER, env={"SK_API_URL": "https://api.example"})
    assert result.exit_code == 0
    assert "0199-res" in result.stdout
    assert "0199-op" in result.stdout
    assert "Registration requested" in result.stdout
    assert "open the link in the e-mail" in result.stdout
    assert calls[0]["given_name"] == "Ana"
    assert calls[0]["family_name"] == "Souza"


def test_rate_limit_tells_how_long_to_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(
            [], ApiRejectedError(429, "x", error_code="RateLimited", retry_after_seconds=30)
        ),
    )
    result = runner.invoke(app, REGISTER, env={"SK_API_URL": "https://api.example"})
    assert result.exit_code == 1
    assert "Wait 30 seconds" in result.stderr


def test_a_rejected_field_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit(
            [],
            ApiRejectedError(400, "Campo inválido", error_code="ValidationFailed", field="email"),
        ),
    )
    result = runner.invoke(app, REGISTER, env={"SK_API_URL": "https://api.example"})
    assert result.exit_code == 2
    assert "Field refused by the API" in result.stderr
    assert "email" in result.stderr


def test_an_unavailable_service_asks_to_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sk.commands.register.submit_registration",
        fake_submit([], ApiUnavailableError("the API answered HTTP 503")),
    )
    result = runner.invoke(app, REGISTER, env={"SK_API_URL": "https://api.example"})
    assert result.exit_code == 1
    assert "Try again in a few minutes" in result.stderr


def test_help_is_in_portuguese_and_lists_the_three_fields() -> None:
    result = runner.invoke(app, ["register", "--help"])
    assert result.exit_code == 0
    for option in ("--name", "--surname", "--email"):
        assert option in result.stdout
    # O endereço da API e a permissão de HTTP são do ambiente, não de opções (decisão 0041).
    for absent in ("--password", "--api-url", "--allow-insecure-http"):
        assert absent not in result.stdout
