import pytest
from pydantic import ValidationError

from core.settings import CoreSettings


def test_defaults_have_no_secrets() -> None:
    settings = CoreSettings()
    assert settings.database.relay_password is None
    assert settings.nats.password is None
    assert settings.auth.audience is None
    assert settings.api.organization_quota == 1


def test_environment_variables_follow_the_section_and_field_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORE_NATS_URL", "nats://example:4222")
    monkeypatch.setenv("CORE_DATABASE_ORGANIZATION_MANAGER_PASSWORD", "segredo")
    monkeypatch.setenv("CORE_API_ORGANIZATION_QUOTA", "3")
    settings = CoreSettings()
    assert settings.nats.url == "nats://example:4222"
    assert settings.api.organization_quota == 3
    password = settings.database.organization_manager_password
    assert password is not None
    assert password.get_secret_value() == "segredo"
    assert "segredo" not in repr(settings)


def test_unknown_field_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORE_NATS_TYPO", "x")
    with pytest.raises(ValidationError):
        CoreSettings()
