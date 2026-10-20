import pytest
from pydantic import ValidationError

from core_account.manager.settings import (
    AccountManagerSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "CORE_ACCOUNT_MANAGER_MESSAGING_URL",
    "CORE_ACCOUNT_MANAGER_MESSAGING_USER",
    "CORE_ACCOUNT_MANAGER_MESSAGING_PASSWORD",
    "CORE_ACCOUNT_MANAGER_DATABASE_HOST",
    "CORE_ACCOUNT_MANAGER_DATABASE_PORT",
    "CORE_ACCOUNT_MANAGER_DATABASE_NAME",
    "CORE_ACCOUNT_MANAGER_DATABASE_USER",
    "CORE_ACCOUNT_MANAGER_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets() -> None:
    settings = AccountManagerSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_MANAGER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("CORE_ACCOUNT_MANAGER_DATABASE_PASSWORD", "segredo")
    settings = AccountManagerSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_MANAGER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountManagerSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(AccountManagerSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(AccountManagerSettings()) == []
