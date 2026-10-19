import pytest
from pydantic import ValidationError

from ipm_organization.manager.settings import (
    OrganizationManagerSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_ORGANIZATION_MANAGER_NATS_PASSWORD",
    "IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD",
)


def test_defaults_have_no_secrets() -> None:
    settings = OrganizationManagerSettings()
    assert settings.database.password is None
    assert settings.nats.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_MANAGER_NATS_URL", "nats://example:4222")
    monkeypatch.setenv("IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD", "segredo")
    settings = OrganizationManagerSettings()
    assert settings.nats.url == "nats://example:4222"
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_MANAGER_NATS_TYPO", "x")
    with pytest.raises(ValidationError):
        OrganizationManagerSettings()


def test_missing_required_lists_every_secret_without_default() -> None:
    assert missing_required(OrganizationManagerSettings()) == list(REQUIRED_SECRETS)


def test_missing_required_is_empty_when_everything_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(OrganizationManagerSettings()) == []
