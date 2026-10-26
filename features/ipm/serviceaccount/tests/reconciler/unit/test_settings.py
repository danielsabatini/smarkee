import pytest
from pydantic import ValidationError

from ipm_serviceaccount.reconciler.settings import (
    ServiceaccountReconcilerSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "IPM_SERVICEACCOUNT_RECONCILER_MESSAGING_URL",
    "IPM_SERVICEACCOUNT_RECONCILER_MESSAGING_USER",
    "IPM_SERVICEACCOUNT_RECONCILER_MESSAGING_PASSWORD",
)


def test_defaults_follow_the_resource_parameters_of_the_contract() -> None:
    loop = ServiceaccountReconcilerSettings().loop
    assert loop.observation_validity_seconds == 600  # PT10M
    assert loop.action_deadline_seconds == 120  # PT2M
    assert ServiceaccountReconcilerSettings().messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECONCILER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECONCILER_MESSAGING_PASSWORD", "segredo")
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS", "30")
    settings = ServiceaccountReconcilerSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.loop.action_deadline_seconds == 30
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPM_SERVICEACCOUNT_RECONCILER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        ServiceaccountReconcilerSettings()


def test_missing_required_lists_the_nats_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(ServiceaccountReconcilerSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(ServiceaccountReconcilerSettings()) == []
