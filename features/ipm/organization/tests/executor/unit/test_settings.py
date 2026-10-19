import pytest
from pydantic import ValidationError

from ipm_organization.executor.settings import (
    OrganizationExecutorSettings,
    missing_required,
)

REQUIRED_SECRETS = ("IPM_ORGANIZATION_EXECUTOR_MESSAGING_PASSWORD",)


def test_defaults_have_no_secrets() -> None:
    settings = OrganizationExecutorSettings()
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_EXECUTOR_IDENTITY_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("IPM_ORGANIZATION_EXECUTOR_MESSAGING_PASSWORD", "segredo")
    settings = OrganizationExecutorSettings()
    assert settings.identity.timeout_seconds == 7.0
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_ORGANIZATION_EXECUTOR_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        OrganizationExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(OrganizationExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(OrganizationExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert OrganizationExecutorSettings().partition.count == 4
    monkeypatch.setenv("IPM_ORGANIZATION_EXECUTOR_PARTITION_COUNT", "8")
    assert OrganizationExecutorSettings().partition.count == 8
