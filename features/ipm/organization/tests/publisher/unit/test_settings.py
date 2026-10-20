import pytest
from pydantic import ValidationError

from ipm_organization.publisher.settings import (
    IpmOrganizationPublisherSettings,
    missing_required,
)

REQUIRED = (
    "IPM_ORGANIZATION_PUBLISHER_MESSAGING_USER",
    "IPM_ORGANIZATION_PUBLISHER_MESSAGING_PASSWORD",
    "IPM_ORGANIZATION_PUBLISHER_DATABASE_USER",
    "IPM_ORGANIZATION_PUBLISHER_DATABASE_PASSWORD",
)


def test_defaults_carry_no_credentials() -> None:
    settings = IpmOrganizationPublisherSettings()
    assert settings.database.user is None
    assert settings.database.password is None
    assert settings.messaging.user is None
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_PUBLISHER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("IPM_ORGANIZATION_PUBLISHER_DATABASE_PASSWORD", "segredo")
    settings = IpmOrganizationPublisherSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_PUBLISHER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        IpmOrganizationPublisherSettings()


def test_missing_required_lists_every_credential_without_default() -> None:
    assert missing_required(IpmOrganizationPublisherSettings()) == list(REQUIRED)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED:
        monkeypatch.setenv(name, "valor")
    assert missing_required(IpmOrganizationPublisherSettings()) == []
