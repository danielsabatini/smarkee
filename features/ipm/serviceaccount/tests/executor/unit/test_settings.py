import pytest
from pydantic import ValidationError

from ipm_serviceaccount.executor.settings import (
    ServiceaccountExecutorSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_SERVICEACCOUNT_EXECUTOR_MESSAGING_URL",
    "IPM_SERVICEACCOUNT_EXECUTOR_MESSAGING_USER",
    "IPM_SERVICEACCOUNT_EXECUTOR_MESSAGING_PASSWORD",
    "IPM_SERVICEACCOUNT_EXECUTOR_IDENTITY_PROJECT_ID",
)


def test_defaults_have_no_secrets() -> None:
    settings = ServiceaccountExecutorSettings()
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_EXECUTOR_IDENTITY_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_EXECUTOR_MESSAGING_PASSWORD", "segredo")
    settings = ServiceaccountExecutorSettings()
    assert settings.identity.timeout_seconds == 7.0
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_EXECUTOR_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        ServiceaccountExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(ServiceaccountExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(ServiceaccountExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ServiceaccountExecutorSettings().partition.count == 4
    monkeypatch.setenv("IPM_SERVICEACCOUNT_EXECUTOR_PARTITION_COUNT", "8")
    assert ServiceaccountExecutorSettings().partition.count == 8
