import pytest
from pydantic import ValidationError

from core_account.observer.settings import (
    AccountObserverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "CORE_ACCOUNT_OBSERVER_MESSAGING_URL",
    "CORE_ACCOUNT_OBSERVER_MESSAGING_USER",
    "CORE_ACCOUNT_OBSERVER_MESSAGING_PASSWORD",
    "CORE_ACCOUNT_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID",
)


def test_defaults_follow_the_contract_and_have_no_secrets() -> None:
    settings = AccountObserverSettings()
    assert settings.loop.observation_interval_seconds == 300  # PT5M
    assert settings.messaging.password is None
    assert (settings.partition.index, settings.partition.count) == (0, 1)
    assert not hasattr(
        settings.identity, "expected_permissions"
    )  # a lista vive no desired (decisão 0025)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_PARTITION_COUNT", "3")
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID", "org-r")
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_MESSAGING_PASSWORD", "segredo")
    settings = AccountObserverSettings()
    assert settings.partition.count == 3
    assert settings.identity.register_organization_id == "org-r"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountObserverSettings()


def test_missing_required_lists_every_value_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert missing_required(AccountObserverSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(AccountObserverSettings()) == []
