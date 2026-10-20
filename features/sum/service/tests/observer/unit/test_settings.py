import pytest
from pydantic import ValidationError

from sum_service.observer.settings import (
    SumServiceObserverSettings,
    missing_required,
)

REQUIRED_SECRETS = (
    "SUM_SERVICE_OBSERVER_MESSAGING_URL",
    "SUM_SERVICE_OBSERVER_MESSAGING_USER",
    "SUM_SERVICE_OBSERVER_MESSAGING_PASSWORD",
    "SUM_SERVICE_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID",
    "SUM_SERVICE_OBSERVER_IDENTITY_PROJECT_IDS",
    "SUM_SERVICE_OBSERVER_CATALOG_ROLES",
)


def test_defaults_follow_the_contract_and_have_no_secrets() -> None:
    settings = SumServiceObserverSettings()
    assert settings.loop.observation_interval_seconds == 300  # PT5M
    assert settings.messaging.password is None
    assert (settings.partition.index, settings.partition.count) == (0, 1)
    assert settings.loop.observation_jitter == 0.2
    assert not hasattr(
        settings.identity, "expected_roles"
    )  # a lista vive no desired (decisão 0025)


def test_environment_variables_follow_the_prefix_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_PARTITION_COUNT", "3")
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID", "org-r")
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_MESSAGING_PASSWORD", "segredo")
    settings = SumServiceObserverSettings()
    assert settings.partition.count == 3
    assert settings.identity.register_organization_id == "org-r"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_MESSAGING_TYPO", "x")
    with pytest.raises(ValidationError):
        SumServiceObserverSettings()


def test_missing_required_lists_every_value_without_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert missing_required(SumServiceObserverSettings()) == list(REQUIRED_SECRETS)
    for name in REQUIRED_SECRETS:
        # Os IDs de projeto são um objeto JSON (módulo → projeto); as demais são texto.
        monkeypatch.setenv(name, '{"ipm": "p"}' if name.endswith("PROJECT_IDS") else "valor")
    assert missing_required(SumServiceObserverSettings()) == []


@pytest.mark.parametrize(("index", "count"), [(1, 1), (3, 2), (-1, 2), (0, 0)])
def test_an_invalid_partition_is_rejected(
    monkeypatch: pytest.MonkeyPatch, index: int, count: int
) -> None:
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_PARTITION_INDEX", str(index))
    monkeypatch.setenv("SUM_SERVICE_OBSERVER_PARTITION_COUNT", str(count))
    with pytest.raises(ValidationError):
        SumServiceObserverSettings()
