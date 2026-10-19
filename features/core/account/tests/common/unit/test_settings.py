"""Seções de configuração comuns (decisão 0063)."""

import pytest
from pydantic import ValidationError

from core_account.common.settings import (
    DatabaseSettings,
    HealthSettings,
    MessagingSettings,
    StateMessagingSettings,
    missing_variables,
)


def test_missing_variables_prefixes_and_keeps_the_order_of_the_ones_not_informed() -> None:
    present = {"A_PASSWORD": False, "B_PASSWORD": True, "C_ID": False}
    assert missing_variables("CORE_ACCOUNT_X_", present) == [
        "CORE_ACCOUNT_X_A_PASSWORD",
        "CORE_ACCOUNT_X_C_ID",
    ]
    assert missing_variables("CORE_ACCOUNT_X_", {"A": True}) == []


def test_the_database_login_role_has_no_default_so_each_role_must_name_its_own() -> None:
    with pytest.raises(ValidationError):
        DatabaseSettings()  # pyright: ignore[reportCallIssue]
    assert DatabaseSettings(user="core_account_x_login").password is None


def test_sections_reject_unknown_fields() -> None:
    for section in (MessagingSettings, HealthSettings, StateMessagingSettings):
        with pytest.raises(ValidationError):
            section(unknown="x")  # pyright: ignore[reportCallIssue]


def test_defaults_have_no_secrets_and_the_state_messaging_adds_the_consumer_inactivity() -> None:
    assert MessagingSettings().password is None
    assert StateMessagingSettings().consumer_inactive_threshold_seconds == 300
    assert HealthSettings().port == 8000
