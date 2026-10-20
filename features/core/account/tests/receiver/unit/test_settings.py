import pytest
from pydantic import ValidationError

from core_account.receiver.settings import (
    AccountReceiverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE",
    "CORE_ACCOUNT_RECEIVER_MESSAGING_USER",
    "CORE_ACCOUNT_RECEIVER_MESSAGING_PASSWORD",
    "CORE_ACCOUNT_RECEIVER_DATABASE_USER",
    "CORE_ACCOUNT_RECEIVER_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets() -> None:
    settings = AccountReceiverSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None
    assert settings.auth.audience is None
    assert settings.api.anonymous_rate_limit == 5


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_RECEIVER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("CORE_ACCOUNT_RECEIVER_DATABASE_PASSWORD", "segredo")
    monkeypatch.setenv("CORE_ACCOUNT_RECEIVER_API_ANONYMOUS_RATE_LIMIT", "3")
    settings = AccountReceiverSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.api.anonymous_rate_limit == 3
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_RECEIVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountReceiverSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(AccountReceiverSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(AccountReceiverSettings()) == []


def test_peers_default_to_localhost() -> None:
    peers = AccountReceiverSettings().peers
    assert peers.organizations_url == "http://localhost:8000"
    assert peers.services_url == "http://localhost:8000"
