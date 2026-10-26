import pytest
from pydantic import ValidationError

from ipm_serviceaccount.receiver.settings import (
    ServiceaccountReceiverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_SERVICEACCOUNT_RECEIVER_AUTH_AUDIENCE",
    "IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_URL",
    "IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_USER",
    "IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_PASSWORD",
    "IPM_SERVICEACCOUNT_RECEIVER_DATABASE_HOST",
    "IPM_SERVICEACCOUNT_RECEIVER_DATABASE_PORT",
    "IPM_SERVICEACCOUNT_RECEIVER_DATABASE_NAME",
    "IPM_SERVICEACCOUNT_RECEIVER_DATABASE_USER",
    "IPM_SERVICEACCOUNT_RECEIVER_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets() -> None:
    settings = ServiceaccountReceiverSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None
    assert settings.auth.audience is None
    assert settings.api.serviceaccount_quota == 5


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_DATABASE_PASSWORD", "segredo")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_API_SERVICEACCOUNT_QUOTA", "3")
    settings = ServiceaccountReceiverSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.api.serviceaccount_quota == 3
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECEIVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        ServiceaccountReceiverSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(ServiceaccountReceiverSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(ServiceaccountReceiverSettings()) == []
