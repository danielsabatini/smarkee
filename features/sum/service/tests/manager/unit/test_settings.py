import pytest
from pydantic import ValidationError

from sum_service.manager.settings import (
    SumServiceManagerSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "SUM_SERVICE_MANAGER_MESSAGING_USER",
    "SUM_SERVICE_MANAGER_MESSAGING_PASSWORD",
    "SUM_SERVICE_MANAGER_DATABASE_USER",
    "SUM_SERVICE_MANAGER_DATABASE_PASSWORD",
    "SUM_SERVICE_MANAGER_CATALOG_ROLES",
)


def test_defaults_have_no_secrets() -> None:
    settings = SumServiceManagerSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_MANAGER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("SUM_SERVICE_MANAGER_DATABASE_PASSWORD", "segredo")
    settings = SumServiceManagerSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_MANAGER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServiceManagerSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(SumServiceManagerSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(SumServiceManagerSettings()) == []
