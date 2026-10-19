import pytest
from pydantic import ValidationError

from core_account.executor.settings import (
    AccountExecutorSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "CORE_ACCOUNT_EXECUTOR_NATS_PASSWORD",
    "CORE_ACCOUNT_EXECUTOR_ZITADEL_REGISTER_ORGANIZATION_ID",
    "CORE_ACCOUNT_EXECUTOR_ZITADEL_PROJECT_IDS",
)


def test_defaults_have_no_secrets_and_no_role_list() -> None:
    settings = AccountExecutorSettings()
    assert settings.nats.password is None
    assert not hasattr(settings.zitadel, "granted_roles")  # as roles vêm do desired (decisão 0025)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_EXECUTOR_ZITADEL_PROJECT_IDS", '{"core": "p-1", "sum": "p-2"}')
    monkeypatch.setenv("CORE_ACCOUNT_EXECUTOR_NATS_PASSWORD", "segredo")
    settings = AccountExecutorSettings()
    assert settings.zitadel.project_ids == {"core": "p-1", "sum": "p-2"}
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_EXECUTOR_NATS_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(AccountExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, '{"core": "p-1"}' if name.endswith("PROJECT_IDS") else "valor")
    assert missing_required(AccountExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert AccountExecutorSettings().partition.count == 4
    monkeypatch.setenv("CORE_ACCOUNT_EXECUTOR_PARTITION_COUNT", "8")
    assert AccountExecutorSettings().partition.count == 8
