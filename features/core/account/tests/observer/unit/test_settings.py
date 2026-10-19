import pytest
from pydantic import ValidationError

from core_account.observer.settings import (
    REQUIRED_SECRETS,
    AccountObserverSettings,
    missing_required,
)


def test_defaults_follow_the_contract_and_have_no_secrets() -> None:
    settings = AccountObserverSettings()
    assert settings.loop.observation_interval_seconds == 300  # PT5M
    assert settings.nats.password is None
    assert (settings.partition.index, settings.partition.count) == (0, 1)
    assert not hasattr(settings.zitadel, "expected_roles")  # a lista vive no desired (decisão 0025)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_PARTITION_COUNT", "3")
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_ZITADEL_REGISTER_ORGANIZATION_ID", "org-r")
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_NATS_PASSWORD", "segredo")
    settings = AccountObserverSettings()
    assert settings.partition.count == 3
    assert settings.zitadel.register_organization_id == "org-r"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_ACCOUNT_OBSERVER_NATS_TYPO", "x")
    with pytest.raises(ValidationError):
        AccountObserverSettings()


def test_missing_required_lists_every_value_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert missing_required(AccountObserverSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "valor")
    assert missing_required(AccountObserverSettings()) == []
