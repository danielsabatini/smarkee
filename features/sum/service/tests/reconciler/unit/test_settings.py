import pytest
from pydantic import ValidationError

from sum_service.reconciler.settings import (
    SumServiceReconcilerSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "SUM_SERVICE_RECONCILER_MESSAGING_URL",
    "SUM_SERVICE_RECONCILER_MESSAGING_USER",
    "SUM_SERVICE_RECONCILER_MESSAGING_PASSWORD",
)


def test_defaults_follow_the_resource_parameters_of_the_contract() -> None:
    loop = SumServiceReconcilerSettings().loop
    assert loop.observation_validity_seconds == 600  # PT10M
    assert loop.action_deadline_seconds == 120  # PT2M
    assert SumServiceReconcilerSettings().messaging.password is None


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_RECONCILER_MESSAGING_URL", "nats://example:4222")
    monkeypatch.setenv("SUM_SERVICE_RECONCILER_MESSAGING_PASSWORD", "segredo")
    monkeypatch.setenv("SUM_SERVICE_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS", "30")
    settings = SumServiceReconcilerSettings()
    assert settings.messaging.url == "nats://example:4222"
    assert settings.loop.action_deadline_seconds == 30
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_RECONCILER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServiceReconcilerSettings()


def test_missing_required_lists_the_nats_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    assert missing_required(SumServiceReconcilerSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        monkeypatch.setenv(name, "5432" if name.endswith("_PORT") else "valor")
    assert missing_required(SumServiceReconcilerSettings()) == []
