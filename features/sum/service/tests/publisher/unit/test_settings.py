import pytest
from pydantic import ValidationError

from sum_service.publisher.settings import (
    SumServicePublisherSettings,
    missing_required,
)

REQUIRED = (
    "SUM_SERVICE_PUBLISHER_MESSAGING_URL",
    "SUM_SERVICE_PUBLISHER_MESSAGING_USER",
    "SUM_SERVICE_PUBLISHER_MESSAGING_PASSWORD",
    "SUM_SERVICE_PUBLISHER_DATABASE_HOST",
    "SUM_SERVICE_PUBLISHER_DATABASE_PORT",
    "SUM_SERVICE_PUBLISHER_DATABASE_NAME",
    "SUM_SERVICE_PUBLISHER_DATABASE_USER",
    "SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD",
)


def test_defaults_carry_no_credentials() -> None:
    settings = SumServicePublisherSettings()
    assert settings.database.user is None
    assert settings.database.password is None
    assert settings.messaging.user is None
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_PUBLISHER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD", "segredo")
    settings = SumServicePublisherSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_PUBLISHER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServicePublisherSettings()


def test_missing_required_lists_every_credential_without_default() -> None:
    assert missing_required(SumServicePublisherSettings()) == list(REQUIRED)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(SumServicePublisherSettings()) == []
