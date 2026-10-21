import pytest
from pydantic import ValidationError

from ipm_user.executor.settings import (
    UserExecutorSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_USER_EXECUTOR_MESSAGING_URL",
    "IPM_USER_EXECUTOR_MESSAGING_USER",
    "IPM_USER_EXECUTOR_MESSAGING_PASSWORD",
    "IPM_USER_EXECUTOR_IDENTITY_PROJECT_ID",
)


def test_defaults_have_no_secrets() -> None:
    settings = UserExecutorSettings()
    assert settings.messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_USER_EXECUTOR_IDENTITY_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("IPM_USER_EXECUTOR_MESSAGING_PASSWORD", "segredo")
    settings = UserExecutorSettings()
    assert settings.identity.timeout_seconds == 7.0
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_USER_EXECUTOR_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        UserExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(UserExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(UserExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert UserExecutorSettings().partition.count == 4
    monkeypatch.setenv("IPM_USER_EXECUTOR_PARTITION_COUNT", "8")
    assert UserExecutorSettings().partition.count == 8
