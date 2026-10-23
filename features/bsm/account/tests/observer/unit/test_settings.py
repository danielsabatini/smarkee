import pytest
from pydantic import ValidationError

from bsm_account.observer.settings import (
    AccountObserverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "BSM_ACCOUNT_OBSERVER_MESSAGING_URL",
    "BSM_ACCOUNT_OBSERVER_MESSAGING_USER",
    "BSM_ACCOUNT_OBSERVER_MESSAGING_PASSWORD",
    "BSM_ACCOUNT_OBSERVER_STORAGE_DIRECTORY",
)


def test_defaults_follow_the_contract_and_have_no_secrets() -> None:
    settings = AccountObserverSettings()
    assert settings.loop.observation_interval_seconds == 300  # PT5M
    assert settings.messaging.password is None
    assert settings.storage.directory is None
    assert (settings.partition.index, settings.partition.count) == (0, 1)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BSM_ACCOUNT_OBSERVER_PARTITION_COUNT", "3")
    monkeypatch.setenv("BSM_ACCOUNT_OBSERVER_STORAGE_DIRECTORY", "/srv/bsm-state")
    monkeypatch.setenv("BSM_ACCOUNT_OBSERVER_MESSAGING_PASSWORD", "segredo")
    settings = AccountObserverSettings()
    assert settings.partition.count == 3
    assert settings.storage.directory == "/srv/bsm-state"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BSM_ACCOUNT_OBSERVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountObserverSettings()


def test_missing_required_lists_every_value_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert missing_required(AccountObserverSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(AccountObserverSettings()) == []
