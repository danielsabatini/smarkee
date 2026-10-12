import pytest
from pydantic import ValidationError

from core_user_executor.settings import REQUIRED_SECRETS, UserExecutorSettings, missing_required


def test_defaults_have_no_secrets_and_the_decision_0014_roles() -> None:
    settings = UserExecutorSettings()
    assert settings.nats.password is None
    assert settings.zitadel.granted_roles == (
        "organization.create",
        "organization.get",
        "organization.list",
        "organization.update",
        "organization.delete",
        "user.get",
        "user.delete",
    )


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_USER_EXECUTOR_ZITADEL_PROJECT_ID", "p-1")
    monkeypatch.setenv("CORE_USER_EXECUTOR_NATS_PASSWORD", "segredo")
    settings = UserExecutorSettings()
    assert settings.zitadel.project_id == "p-1"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_USER_EXECUTOR_NATS_TYPO", "x")
    with pytest.raises(ValidationError):
        UserExecutorSettings()


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(UserExecutorSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(UserExecutorSettings()) == []


def test_partition_count_defaults_to_the_bootstrap_value_and_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert UserExecutorSettings().partition.count == 4
    monkeypatch.setenv("CORE_USER_EXECUTOR_PARTITION_COUNT", "8")
    assert UserExecutorSettings().partition.count == 8
