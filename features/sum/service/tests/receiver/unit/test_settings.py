import pytest
from pydantic import ValidationError

from sum_service.receiver.settings import (
    SumServiceReceiverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "SUM_SERVICE_RECEIVER_AUTH_AUDIENCE",
    "SUM_SERVICE_RECEIVER_MESSAGING_PASSWORD",
    "SUM_SERVICE_RECEIVER_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets() -> None:
    settings = SumServiceReceiverSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None
    assert settings.auth.audience is None
    assert settings.api.port == 8000


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_RECEIVER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("SUM_SERVICE_RECEIVER_DATABASE_PASSWORD", "segredo")
    monkeypatch.setenv("SUM_SERVICE_RECEIVER_API_PORT", "9000")
    settings = SumServiceReceiverSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.api.port == 9000
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_RECEIVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServiceReceiverSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(SumServiceReceiverSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(SumServiceReceiverSettings()) == []
