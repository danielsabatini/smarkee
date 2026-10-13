import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sk.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.main import app
from sk.oidc import OidcError, ProviderMetadata

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in ("SK_AUTH_ISSUER", "SK_AUTH_CLIENT_ID", "SK_AUTH_ALLOW_INSECURE_HTTP"):
        monkeypatch.delenv(variable, raising=False)


def test_login_without_issuer_is_a_usage_error() -> None:
    result = runner.invoke(app, ["auth", "login", "--client-id", "client-1"])
    assert result.exit_code == 2
    assert "SK_AUTH_ISSUER" in result.stderr


def test_login_without_client_id_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SK_AUTH_ISSUER", "https://issuer.example")
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "SK_AUTH_CLIENT_ID" in result.stderr


def test_http_issuer_is_refused_without_explicit_permission() -> None:
    result = runner.invoke(
        app, ["auth", "login", "--issuer", "http://issuer.example", "--client-id", "client-1"]
    )
    assert result.exit_code == 1
    assert "sem TLS" in result.stderr


def test_invalid_config_file_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text("[auth]\nunknown = 1\n", encoding="utf-8")
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "Configuração inválida" in result.stderr


def test_snake_case_key_in_config_file_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(
        '[auth]\nclient_id = "client-1"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "camelCase" in result.stderr


def test_init_writes_camel_case_config_with_private_permissions(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "auth",
            "init",
            "--issuer",
            "http://ipm-dev.smarkee.com.br:8080",
            "--client-id",
            "394397791373230085",
            "--allow-insecure-http",
        ],
    )
    assert result.exit_code == 0, result.stderr
    config_file = tmp_path / "sk" / "config.toml"
    assert config_file.read_text(encoding="utf-8") == (
        "[auth]\n"
        'issuer = "http://ipm-dev.smarkee.com.br:8080"\n'
        'clientId = "394397791373230085"\n'
        "allowInsecureHttp = true\n"
    )
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_file.parent.stat().st_mode) & 0o077 == 0


def test_init_takes_values_from_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SK_AUTH_ISSUER", "https://issuer.example")
    monkeypatch.setenv("SK_AUTH_CLIENT_ID", "env-client")
    result = runner.invoke(app, ["auth", "init"])
    assert result.exit_code == 0, result.stderr
    assert 'clientId = "env-client"' in (tmp_path / "sk" / "config.toml").read_text(
        encoding="utf-8"
    )


def test_init_requires_client_id() -> None:
    result = runner.invoke(app, ["auth", "init", "--issuer", "https://issuer.example"])
    assert result.exit_code == 2
    assert "SK_AUTH_CLIENT_ID" in result.stderr


def test_init_refuses_http_issuer_without_explicit_permission(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["auth", "init", "--issuer", "http://issuer.example", "--client-id", "client-1"]
    )
    assert result.exit_code == 2
    assert "sem TLS" in result.stderr
    assert not (tmp_path / "sk" / "config.toml").exists()


def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None:
    (tmp_path / "sk").mkdir()
    config_file = tmp_path / "sk" / "config.toml"
    config_file.write_text("[auth]\nclient_id = 'broken'\n", encoding="utf-8")
    arguments = ["auth", "init", "--issuer", "https://issuer.example", "--client-id", "new"]

    result = runner.invoke(app, arguments)
    assert result.exit_code == 2
    assert "--force" in result.stderr
    assert "broken" in config_file.read_text(encoding="utf-8")

    # Com --force, o arquivo existente (mesmo inválido) não é lido: é substituído.
    result = runner.invoke(app, [*arguments, "--force"])
    assert result.exit_code == 0, result.stderr
    assert 'clientId = "new"' in config_file.read_text(encoding="utf-8")


def test_auth_without_subcommand_shows_help() -> None:
    result = runner.invoke(app, ["auth"])
    assert "login" in result.output


def write_session(expires_at: datetime) -> None:
    save_credentials(
        default_credentials_path(),
        StoredCredentials(
            issuer="https://issuer.example",
            client_id="client-1",
            token_type="Bearer",
            access_token="TOKEN-SECRETO-1",
            access_token_expires_at=expires_at,
            refresh_token=None,
            id_token=None,
            scope=None,
            obtained_at=expires_at - timedelta(hours=1),
        ),
    )


def provider_metadata() -> ProviderMetadata:
    return ProviderMetadata(
        issuer="https://issuer.example",
        authorization_endpoint="https://issuer.example/authorize",
        token_endpoint="https://issuer.example/token",
        userinfo_endpoint="https://issuer.example/userinfo",
    )


def fake_metadata(*_args: object, **_kwargs: object) -> ProviderMetadata:
    return provider_metadata()


def test_whoami_without_session_asks_to_login() -> None:
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 1
    assert "Não autenticado" in result.stderr
    assert "sk auth login" in result.stderr


def test_whoami_with_expired_access_does_not_call_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_be_called(*_args: object) -> None:
        raise AssertionError("o provedor não deve ser consultado com o acesso vencido")

    monkeypatch.setattr("sk.commands.auth.fetch_userinfo", must_not_be_called)
    write_session(datetime.now(UTC) - timedelta(minutes=1))
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 1
    assert "Sessão expirada" in result.stderr


def test_whoami_shows_the_user_and_hides_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_userinfo(*_args: object) -> dict[str, object]:
        return {"preferred_username": "ana@example.com"}

    monkeypatch.setattr("sk.commands.auth.fetch_provider_metadata", fake_metadata)
    monkeypatch.setattr("sk.commands.auth.fetch_userinfo", fake_userinfo)
    write_session(datetime.now(UTC) + timedelta(hours=1))
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 0
    assert "Sessão ativa" in result.stdout
    assert "ana@example.com" in result.stdout
    assert "TOKEN-SECRETO-1" not in result.output


def test_whoami_reports_when_the_provider_does_not_confirm_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sk.commands.auth.fetch_provider_metadata", fake_metadata)

    def rejected(*_args: object) -> None:
        raise OidcError("consulta do userinfo: o provedor respondeu HTTP 401")

    monkeypatch.setattr("sk.commands.auth.fetch_userinfo", rejected)
    write_session(datetime.now(UTC) + timedelta(hours=1))
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 1
    assert "Não foi possível confirmar a sessão" in result.stderr
    assert "HTTP 401" in result.stderr
    assert "TOKEN-SECRETO-1" not in result.output
