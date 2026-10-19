import pytest
from pydantic import ValidationError

from sum_service.executor.settings import (
    SumServiceExecutorSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "SUM_SERVICE_EXECUTOR_MESSAGING_PASSWORD",
    "SUM_SERVICE_EXECUTOR_IDENTITY_REGISTER_ORGANIZATION_ID",
    "SUM_SERVICE_EXECUTOR_IDENTITY_PROJECT_IDS",
    "SUM_SERVICE_EXECUTOR_CATALOG_ROLES",
)


def test_defaults_have_no_secrets_and_no_role_list() -> None:
    settings = SumServiceExecutorSettings()
    assert settings.messaging.password is None
    assert not hasattr(settings.identity, "granted_roles")  # as roles vêm do desired (decisão 0025)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_IDENTITY_PROJECT_IDS", '{"core": "p-1", "sum": "p-2"}')
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_MESSAGING_PASSWORD", "segredo")
    settings = SumServiceExecutorSettings()
    assert settings.identity.project_ids == {"core": "p-1", "sum": "p-2"}
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServiceExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(SumServiceExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, '{"core": "p-1"}' if name.endswith("PROJECT_IDS") else "valor")
    assert missing_required(SumServiceExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert SumServiceExecutorSettings().partition.count == 4
    monkeypatch.setenv("SUM_SERVICE_EXECUTOR_PARTITION_COUNT", "8")
    assert SumServiceExecutorSettings().partition.count == 8
