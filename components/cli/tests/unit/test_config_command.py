from pathlib import Path

import pytest
from typer.testing import CliRunner

from sk.commands.config import known_keys
from sk.main import app

runner = CliRunner()


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


def create_defaults() -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stderr


def test_keys_come_from_the_models() -> None:
    keys = known_keys()
    assert {"auth.issuer", "auth.clientId", "auth.allowInsecureHttp"} <= set(keys)
    assert {"core.apiUrl", "core.allowInsecureHttp"} <= set(keys)
    assert keys["auth.allowInsecureHttp"].is_boolean
    assert not keys["auth.issuer"].is_boolean


def test_list_shows_the_stored_values() -> None:
    create_defaults()
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0, result.stderr
    assert "auth.issuer" in result.stdout
    assert "https://ipm.smarkee.com.br" in result.stdout


def test_list_without_file_says_to_run_init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0
    assert "sk init" in result.stdout
    assert not config_file(tmp_path).exists()


def test_get_prints_only_the_value() -> None:
    create_defaults()
    result = runner.invoke(app, ["config", "get", "auth.issuer"])
    assert result.exit_code == 0
    assert result.stdout == "https://ipm.smarkee.com.br\n"


def test_get_unknown_key_is_a_usage_error() -> None:
    create_defaults()
    result = runner.invoke(app, ["config", "get", "auth.inexistente"])
    assert result.exit_code == 2
    assert "Chave desconhecida" in result.stderr


def test_get_key_without_value_fails_with_hint(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text(
        '[auth]\nissuer = "https://issuer.example"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["config", "get", "core.apiUrl"])
    assert result.exit_code == 1
    assert "Não definido" in result.stderr


def test_set_changes_only_the_given_key(tmp_path: Path) -> None:
    create_defaults()
    result = runner.invoke(app, ["config", "set", "core.apiUrl", "https://api.other.example"])
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert 'apiUrl = "https://api.other.example"' in text
    assert 'issuer = "https://ipm.smarkee.com.br"' in text
    assert 'clientId = "pendente-prd"' in text


def test_set_boolean_accepts_true_and_false(tmp_path: Path) -> None:
    create_defaults()
    result = runner.invoke(app, ["config", "set", "auth.allowInsecureHttp", "true"])
    assert result.exit_code == 0, result.stderr
    assert "allowInsecureHttp = true" in config_file(tmp_path).read_text(encoding="utf-8")


def test_set_boolean_rejects_other_values(tmp_path: Path) -> None:
    create_defaults()
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "set", "auth.allowInsecureHttp", "sim"])
    assert result.exit_code == 2
    assert "true ou false" in result.stderr
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_set_url_must_have_a_scheme(tmp_path: Path) -> None:
    create_defaults()
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "set", "core.apiUrl", "api.example"])
    assert result.exit_code == 2
    assert "http:// ou https://" in result.stderr
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_set_http_without_permission_warns(tmp_path: Path) -> None:
    create_defaults()
    result = runner.invoke(app, ["config", "set", "core.apiUrl", "http://api.example"])
    assert result.exit_code == 0, result.stderr
    assert "HTTP sem permissão" in result.stderr
    assert 'apiUrl = "http://api.example"' in config_file(tmp_path).read_text(encoding="utf-8")


def test_set_without_file_says_to_run_init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "auth.issuer", "https://issuer.example"])
    assert result.exit_code == 2
    assert "sk init" in result.stderr
    assert not config_file(tmp_path).exists()


def test_set_refuses_a_file_with_invalid_keys(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text("[auth]\nclient_id = 'x'\n", encoding="utf-8")
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "set", "auth.issuer", "https://issuer.example"])
    assert result.exit_code == 2
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_missing_arguments_are_usage_errors() -> None:
    result = runner.invoke(app, ["config", "get"])
    assert result.exit_code == 2
    assert "Argumento obrigatório ausente" in result.stderr
    result = runner.invoke(app, ["config", "set", "auth.issuer"])
    assert result.exit_code == 2
    assert "o valor" in result.stderr
