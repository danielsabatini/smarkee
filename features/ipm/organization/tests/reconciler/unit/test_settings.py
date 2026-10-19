import pytest
from pydantic import ValidationError

from ipm_organization.reconciler.settings import (
    OrganizationReconcilerSettings,
    missing_required,
)

REQUIRED_SECRETS = ("IPM_ORGANIZATION_RECONCILER_MESSAGING_PASSWORD",)


def test_defaults_follow_the_resource_parameters_of_the_contract() -> None:
    loop = OrganizationReconcilerSettings().loop
    assert loop.observation_validity_seconds == 600  # PT10M
    assert loop.action_deadline_seconds == 120  # PT2M
    assert OrganizationReconcilerSettings().messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_RECONCILER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("IPM_ORGANIZATION_RECONCILER_MESSAGING_PASSWORD", "segredo")
    monkeypatch.setenv("IPM_ORGANIZATION_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS", "30")
    settings = OrganizationReconcilerSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.loop.action_deadline_seconds == 30
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_RECONCILER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        OrganizationReconcilerSettings()


def test_missing_required_lists_the_nats_password(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(OrganizationReconcilerSettings()) == list(REQUIRED_SECRETS)
    monkeypatch.setenv(REQUIRED_SECRETS[0], "valor")
    assert missing_required(OrganizationReconcilerSettings()) == []
