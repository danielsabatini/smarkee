import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sk.main import app

runner = CliRunner()

PRD_FILE = (
    "[auth]\n"
    'issuer = "https://ipm.smarkee.com.br"\n'
    'clientId = "pendente-prd"\n'
    "allowInsecureHttp = false\n"
    "\n"
    "[core]\n"
    'apiUrl = "https://api.smarkee.com.br"\n'
    "allowInsecureHttp = false\n"
)


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in (
        "SK_AUTH_ISSUER",
        "SK_AUTH_CLIENT_ID",
        "SK_AUTH_ALLOW_INSECURE_HTTP",
        "SK_CORE_API_URL",
        "SK_CORE_ALLOW_INSECURE_HTTP",
    ):
        monkeypatch.delenv(variable, raising=False)


def config_file(tmp_path: Path) -> Path:
    return tmp_path / "sk" / "config.toml"


def test_init_without_options_writes_production_defaults(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stderr
    assert config_file(tmp_path).read_text(encoding="utf-8") == PRD_FILE
    assert stat.S_IMODE(config_file(tmp_path).stat().st_mode) == 0o600


def test_init_warns_that_the_production_client_id_is_pending() -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "client ID de produção ainda não foi definido" in result.stderr


def test_parameters_replace_the_defaults(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "init",
            "--issuer",
            "https://issuer.example",
            "--client-id",
            "client-1",
            "--api-url",
            "https://api.example",
        ],
    )
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert 'issuer = "https://issuer.example"' in text
    assert 'clientId = "client-1"' in text
    assert 'apiUrl = "https://api.example"' in text
    assert "pendente-prd" not in text
    assert "client ID de produção" not in result.stderr


def test_environment_variables_replace_the_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SK_AUTH_CLIENT_ID", "env-client")
    monkeypatch.setenv("SK_CORE_API_URL", "https://env.example")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert 'clientId = "env-client"' in text
    assert 'apiUrl = "https://env.example"' in text


def test_allow_insecure_http_applies_to_both_sections(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "init",
            "--issuer",
            "http://issuer.example",
            "--api-url",
            "http://api.example",
            "--allow-insecure-http",
        ],
    )
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert text.count("allowInsecureHttp = true") == 2


def test_http_is_refused_without_explicit_permission(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--issuer", "http://issuer.example"])
    assert result.exit_code == 2
    assert "sem TLS" in result.stderr
    assert not config_file(tmp_path).exists()


def test_existing_file_is_kept_without_force(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text("[auth]\nclient_id = 'broken'\n", encoding="utf-8")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 2
    assert "--force" in result.stderr
    assert "broken" in config_file(tmp_path).read_text(encoding="utf-8")


def test_force_replaces_the_existing_file(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text("[auth]\nclient_id = 'broken'\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.stderr
    assert config_file(tmp_path).read_text(encoding="utf-8") == PRD_FILE
