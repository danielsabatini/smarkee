import pytest
from pydantic import ValidationError

from ipm_organization.api.settings import (
    OrganizationApiSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_ORGANIZATION_API_AUTH_AUDIENCE",
    "IPM_ORGANIZATION_API_MESSAGING_URL",
    "IPM_ORGANIZATION_API_MESSAGING_USER",
    "IPM_ORGANIZATION_API_MESSAGING_PASSWORD",
    "IPM_ORGANIZATION_API_DATABASE_HOST",
    "IPM_ORGANIZATION_API_DATABASE_PORT",
    "IPM_ORGANIZATION_API_DATABASE_NAME",
    "IPM_ORGANIZATION_API_DATABASE_USER",
    "IPM_ORGANIZATION_API_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets() -> None:
    settings = OrganizationApiSettings()
    assert settings.database.password is None
    assert settings.messaging.password is None
    assert settings.auth.audience is None
    assert settings.api.organization_quota == 1


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_API_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("IPM_ORGANIZATION_API_DATABASE_PASSWORD", "segredo")
    monkeypatch.setenv("IPM_ORGANIZATION_API_API_ORGANIZATION_QUOTA", "3")
    settings = OrganizationApiSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.api.organization_quota == 3
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_API_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        OrganizationApiSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(OrganizationApiSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(OrganizationApiSettings()) == []
