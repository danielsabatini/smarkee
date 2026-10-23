import pytest
from pydantic import ValidationError

from bsm_account.executor.settings import (
    AccountExecutorSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "BSM_ACCOUNT_EXECUTOR_MESSAGING_URL",
    "BSM_ACCOUNT_EXECUTOR_MESSAGING_USER",
    "BSM_ACCOUNT_EXECUTOR_MESSAGING_PASSWORD",
    "BSM_ACCOUNT_EXECUTOR_STORAGE_DIRECTORY",
)


def test_defaults_have_no_secrets() -> None:
    settings = AccountExecutorSettings()
    assert settings.messaging.password is None
    assert settings.storage.directory is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BSM_ACCOUNT_EXECUTOR_STORAGE_DIRECTORY", "/srv/bsm-state")
    monkeypatch.setenv("BSM_ACCOUNT_EXECUTOR_MESSAGING_PASSWORD", "segredo")
    settings = AccountExecutorSettings()
    assert settings.storage.directory == "/srv/bsm-state"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BSM_ACCOUNT_EXECUTOR_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(AccountExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(AccountExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert AccountExecutorSettings().partition.count == 4
    monkeypatch.setenv("BSM_ACCOUNT_EXECUTOR_PARTITION_COUNT", "8")
    assert AccountExecutorSettings().partition.count == 8
