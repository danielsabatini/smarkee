import pytest
from pydantic import ValidationError

from ipm_organization_observer.settings import (
    REQUIRED_SECRETS,
    OrganizationObserverSettings,
    missing_required,
)


def test_defaults_follow_the_contract_and_have_no_secrets() -> None:
    settings = OrganizationObserverSettings()
    assert settings.loop.observation_interval_seconds == 300  # PT5M
    assert settings.nats.password is None
    assert (settings.partition.index, settings.partition.count) == (0, 1)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_OBSERVER_PARTITION_COUNT", "3")
    monkeypatch.setenv("IPM_ORGANIZATION_OBSERVER_ZITADEL_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("IPM_ORGANIZATION_OBSERVER_NATS_PASSWORD", "segredo")
    settings = OrganizationObserverSettings()
    assert settings.partition.count == 3
    assert settings.zitadel.timeout_seconds == 9.0
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_OBSERVER_NATS_TYPO", "x")
    with pytest.raises(ValidationError):
        OrganizationObserverSettings()


def test_missing_required_lists_every_value_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert missing_required(OrganizationObserverSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(OrganizationObserverSettings()) == []
