"""Seções de configuração comuns (decisão 0063)."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from ipm_serviceaccount.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    RoleSettings,
    Section,
    StateMessagingSettings,
    load_settings,
    missing_variables,
    role_config,
)


def test_missing_variables_prefixes_and_keeps_the_order_of_the_ones_not_informed() -> None:
    present = {"A_PASSWORD": False, "B_PASSWORD": True, "C_ID": False}
    assert missing_variables("IPM_SERVICEACCOUNT_X_", present) == [
        "IPM_SERVICEACCOUNT_X_A_PASSWORD",
        "IPM_SERVICEACCOUNT_X_C_ID",
    ]
    assert missing_variables("IPM_SERVICEACCOUNT_X_", {"A": True}) == []


def test_connection_and_credentials_have_no_default_in_the_code() -> None:
    database = DatabaseSettings()
    assert (database.host, database.port, database.name) == (None, None, None)
    assert (database.user, database.password) == (None, None)
    messaging = MessagingSettings()
    assert (messaging.url, messaging.user, messaging.password) == (None, None, None)


def test_sections_reject_unknown_fields() -> None:
    for section in (MessagingSettings, HealthSettings, StateMessagingSettings):
        with pytest.raises(ValidationError):
            section(unknown="x")  # pyright: ignore[reportCallIssue]


def test_defaults_have_no_secrets_and_the_state_messaging_adds_the_consumer_inactivity() -> None:
    assert MessagingSettings().password is None
    assert StateMessagingSettings().consumer_inactive_threshold_seconds == 300
    assert HealthSettings().port == 8000


# ------------------------------------------------------------ fontes e precedência (decisão 0067)


class _Messaging(Section):
    url: str | None = None
    user: str | None = None
    password: SecretStr | None = None


class _Settings(RoleSettings):
    model_config = role_config("receiver")

    messaging: _Messaging = _Messaging()


TABLE = "[tool.ipm.serviceaccount.receiver.messaging]"


@pytest.fixture
def config_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("SMARKEE_CONFIG_PATH", str(path))
    return path


@pytest.fixture
def secrets_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "secrets"
    path.mkdir()
    monkeypatch.setenv("SMARKEE_SECRETS_DIR", str(path))
    return path


def test_without_file_secrets_or_environment_the_defaults_apply() -> None:
    assert _Settings().messaging.url is None


def test_config_toml_overrides_the_default_using_only_the_table_of_the_role(
    config_toml: Path,
) -> None:
    config_toml.write_text(
        f'{TABLE}\nurl = "nats://do-toml:4222"\n'
        '[tool.ipm.serviceaccount.executor.messaging]\nurl = "nats://de-outro-papel:4222"\n',
        encoding="utf-8",
    )
    assert _Settings().messaging.url == "nats://do-toml:4222"


def test_environment_overrides_config_toml(
    config_toml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_toml.write_text(f'{TABLE}\nurl = "nats://do-toml:4222"\n', encoding="utf-8")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_URL", "nats://do-ambiente:4222")
    assert _Settings().messaging.url == "nats://do-ambiente:4222"


def test_config_toml_without_the_table_of_the_role_is_ignored(config_toml: Path) -> None:
    config_toml.write_text('[tool.outro]\nurl = "x"\n', encoding="utf-8")
    assert _Settings().messaging.url is None


def test_user_comes_from_config_toml_and_the_environment_overrides_it(
    config_toml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_toml.write_text(f'{TABLE}\nuser = "do-toml"\n', encoding="utf-8")
    assert _Settings().messaging.user == "do-toml"
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_USER", "do-ambiente")
    assert _Settings().messaging.user == "do-ambiente"


def test_unknown_field_in_config_toml_is_rejected(config_toml: Path) -> None:
    config_toml.write_text(f'{TABLE}\nurll = "x"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        _Settings()


def test_secret_comes_from_the_file_named_after_the_full_variable(secrets_dir: Path) -> None:
    secret = secrets_dir / "IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_PASSWORD"
    secret.write_text("segredo\n", encoding="utf-8")
    password = _Settings().messaging.password
    assert password is not None
    assert password.get_secret_value() == "segredo"


def test_environment_overrides_the_secret_file(
    secrets_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = secrets_dir / "IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_PASSWORD"
    secret.write_text("do-arquivo", encoding="utf-8")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_PASSWORD", "do-ambiente")
    password = _Settings().messaging.password
    assert password is not None
    assert password.get_secret_value() == "do-ambiente"


def test_command_line_overrides_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_URL", "nats://do-ambiente:4222")
    settings = load_settings(_Settings, ["--messaging.url", "nats://da-cli:4222"])
    assert settings.messaging.url == "nats://da-cli:4222"


def test_secret_on_the_command_line_is_refused() -> None:
    with pytest.raises(SystemExit, match="secrets are not accepted"):
        load_settings(_Settings, ["--messaging.password", "segredo"])
    with pytest.raises(SystemExit, match="secrets are not accepted"):
        load_settings(_Settings, ["--messaging", '{"password": "segredo"}'])


def test_without_arguments_the_pytest_command_line_is_not_parsed() -> None:
    assert load_settings(_Settings).messaging.url is None


def test_every_role_has_the_log_section_with_quiet_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (_Settings().log.level, _Settings().log.dependencies_level) == ("INFO", "WARNING")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_LOG_DEPENDENCIES_LEVEL", "INFO")
    assert (_Settings().log.level, _Settings().log.dependencies_level) == ("DEBUG", "INFO")


def test_an_unknown_log_level_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValidationError):
        _Settings()
