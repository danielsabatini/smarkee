import pytest
from pydantic import ValidationError

from ipm_user.observer.settings import (
    UserObserverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_USER_OBSERVER_MESSAGING_URL",
    "IPM_USER_OBSERVER_MESSAGING_USER",
    "IPM_USER_OBSERVER_MESSAGING_PASSWORD",
    "IPM_USER_OBSERVER_IDENTITY_PROJECT_ID",
)


def test_defaults_follow_the_contract_and_have_no_secrets() -> None:
    settings = UserObserverSettings()
    assert settings.loop.observation_interval_seconds == 300  # PT5M
    assert settings.messaging.password is None
    assert (settings.partition.index, settings.partition.count) == (0, 1)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_USER_OBSERVER_PARTITION_COUNT", "3")
    monkeypatch.setenv("IPM_USER_OBSERVER_IDENTITY_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("IPM_USER_OBSERVER_MESSAGING_PASSWORD", "segredo")
    settings = UserObserverSettings()
    assert settings.partition.count == 3
    assert settings.identity.timeout_seconds == 9.0
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_USER_OBSERVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        UserObserverSettings()


def test_missing_required_lists_every_value_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert missing_required(UserObserverSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(UserObserverSettings()) == []
