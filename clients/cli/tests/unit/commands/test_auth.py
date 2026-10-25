from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sk.identity.credentials import StoredCredentials, default_credentials_path, save_credentials
from sk.identity.oidc import OidcError, ProviderMetadata
from sk.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in ("SK_AUTH_ISSUER", "SK_AUTH_CLIENT_ID", "SK_AUTH_ALLOW_INSECURE_HTTP"):
        monkeypatch.delenv(variable, raising=False)


PLATFORM_VARIABLES = {
    "SK_AUTH_CLIENT_ID": "client-1",
    "SK_CORE_PROJECT_ID": "111",
    "SK_SUM_PROJECT_ID": "222",
    "SK_IPM_PROJECT_ID": "333",
}


def configure_platform(monkeypatch: pytest.MonkeyPatch, **omitted: bool) -> None:
    """Dá valor ao que ainda não tem padrão de produção (client ID e IDs dos projetos)."""
    for name, value in PLATFORM_VARIABLES.items():
        if not omitted.get(name.lower()):
            monkeypatch.setenv(name, value)


def test_login_refuses_the_production_values_that_do_not_exist_yet() -> None:
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "Production is not provisioned yet" in result.stderr
    for key in ("auth.clientId", "core.projectId", "sum.projectId", "ipm.projectId"):
        assert key in result.stderr
    assert "sk config set" in result.stderr


def test_login_names_only_the_values_that_are_still_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_platform(monkeypatch, sk_ipm_project_id=True)
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "ipm.projectId" in result.stderr
    assert "auth.clientId" not in result.stderr and "sum.projectId" not in result.stderr


def test_http_issuer_is_refused_without_explicit_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_platform(monkeypatch)
    monkeypatch.setenv("SK_AUTH_ISSUER", "http://issuer.example")
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 1
    assert "without TLS" in result.stderr


def test_invalid_config_file_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text("[auth]\nunknown = 1\n", encoding="utf-8")
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "Invalid configuration" in result.stderr


def test_snake_case_key_in_config_file_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "sk").mkdir()
    (tmp_path / "sk" / "config.toml").write_text(
        '[auth]\nclient_id = "client-1"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["auth", "login"])
    assert result.exit_code == 2
    assert "camelCase" in result.stderr


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
    assert "Not authenticated" in result.stderr
    assert "sk auth login" in result.stderr


def test_whoami_with_expired_access_and_no_refresh_token_asks_to_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_be_called(*_args: object) -> None:
        raise AssertionError("o provedor não deve ser consultado sem como renovar o acesso")

    monkeypatch.setattr("sk.commands.auth.fetch_userinfo", must_not_be_called)
    write_session(datetime.now(UTC) - timedelta(minutes=1))
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 1
    assert "Session expired" in result.stderr
    assert "sk auth login" in result.stderr


def test_whoami_renews_an_expired_access_with_the_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_userinfo(_metadata: object, token: str) -> dict[str, object]:
        seen.append(token)
        return {"preferred_username": "ana@example.com"}

    def renewed(*_args: object, **_kwargs: object) -> str:
        return "TOKEN-NOVO"

    monkeypatch.setattr("sk.commands.auth.fetch_provider_metadata", fake_metadata)
    monkeypatch.setattr("sk.commands.auth.fetch_userinfo", fake_userinfo)
    monkeypatch.setattr("sk.commands.auth.current_access_token", renewed)
    write_session(datetime.now(UTC) - timedelta(minutes=1))
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 0, result.stderr
    assert seen == ["TOKEN-NOVO"]  # o provedor é consultado com o token renovado
    assert "TOKEN-NOVO" not in result.output


def test_whoami_shows_the_user_and_hides_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_userinfo(*_args: object) -> dict[str, object]:
        return {"preferred_username": "ana@example.com"}

    monkeypatch.setattr("sk.commands.auth.fetch_provider_metadata", fake_metadata)
    monkeypatch.setattr("sk.commands.auth.fetch_userinfo", fake_userinfo)
    write_session(datetime.now(UTC) + timedelta(hours=1))
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == 0
    assert "Active session" in result.stdout
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
    assert "Could not confirm the session" in result.stderr
    assert "HTTP 401" in result.stderr
    assert "TOKEN-SECRETO-1" not in result.output


def test_login_asks_for_the_audience_of_each_configured_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sk.commands.auth import LOGIN_SCOPES, login_scopes, module_project_ids

    assert login_scopes(()) == LOGIN_SCOPES
    projects = ("394490764261851138", "395263163731279883", "395263163630616587")
    scopes = login_scopes(projects)
    for project in projects:
        assert f"urn:zitadel:iam:org:project:id:{project}:aud" in scopes
    assert scopes.count("urn:zitadel:iam:org:projects:roles") == 1
    assert scopes[: len(LOGIN_SCOPES)] == LOGIN_SCOPES

    configure_platform(monkeypatch)
    monkeypatch.setenv("SK_BSM_PROJECT_ID", "444")
    monkeypatch.setenv("SK_OPERATOR_PROJECT_ID", "555")
    assert module_project_ids() == ("111", "222", "333", "444", "555")


def test_refresh_renews_the_session_and_shows_the_new_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expires_at = datetime(2026, 10, 16, 13, 5, tzinfo=UTC)

    def renewed(*_: object, **__: object) -> datetime:
        return expires_at

    monkeypatch.setattr("sk.commands.auth.renew_session", renewed)
    result = runner.invoke(app, ["auth", "refresh"])
    assert result.exit_code == 0, result.stderr
    assert "Session renewed" in result.stdout


def test_refresh_without_a_session_asks_for_login() -> None:
    result = runner.invoke(app, ["auth", "refresh"])
    assert result.exit_code == 1
    assert "sk auth login" in result.stderr
