import pytest
from pydantic import ValidationError

from core_account.publisher.settings import (
    CoreAccountPublisherSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "CORE_ACCOUNT_PUBLISHER_MESSAGING_PASSWORD",
    "CORE_ACCOUNT_PUBLISHER_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets_and_use_the_publisher_role() -> None:
    settings = CoreAccountPublisherSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None
    assert settings.database.user == "core_account_publisher_login"


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_PUBLISHER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("CORE_ACCOUNT_PUBLISHER_DATABASE_PASSWORD", "segredo")
    settings = CoreAccountPublisherSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_PUBLISHER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        CoreAccountPublisherSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(CoreAccountPublisherSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(CoreAccountPublisherSettings()) == []
