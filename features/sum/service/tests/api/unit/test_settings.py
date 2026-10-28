import pytest
from pydantic import ValidationError

from sum_service.api.settings import (
    SumServiceApiSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "SUM_SERVICE_API_AUTH_AUDIENCE",
    "SUM_SERVICE_API_MESSAGING_URL",
    "SUM_SERVICE_API_MESSAGING_USER",
    "SUM_SERVICE_API_MESSAGING_PASSWORD",
    "SUM_SERVICE_API_DATABASE_HOST",
    "SUM_SERVICE_API_DATABASE_PORT",
    "SUM_SERVICE_API_DATABASE_NAME",
    "SUM_SERVICE_API_DATABASE_USER",
    "SUM_SERVICE_API_DATABASE_PASSWORD",
    "SUM_SERVICE_API_CATALOG_PERMISSIONS",
)


def test_defaults_have_no_secrets() -> None:
    settings = SumServiceApiSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None
    assert settings.auth.audience is None
    assert settings.catalog.permissions is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_API_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("SUM_SERVICE_API_DATABASE_PASSWORD", "segredo")
    monkeypatch.setenv("SUM_SERVICE_API_API_PORT", "9000")
    settings = SumServiceApiSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.api.port == 9000
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_API_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServiceApiSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(SumServiceApiSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(SumServiceApiSettings()) == []
