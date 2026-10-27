"""A visão `Account` da API: só os campos do contrato, campo a campo."""

from collections.abc import Mapping
from datetime import UTC, datetime

from core_account.api.domain.records import ResourceRecord
from core_account.api.domain.views import account_view

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def record(desired: Mapping[str, object], *, observed_generation: int | None) -> ResourceRecord:
    return ResourceRecord(
        resource_id="acc-1",
        resource_version=2,
        desired_generation=2,
        observed_generation=observed_generation,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=dict(desired),
        presence="present",
        observed={
            "emailVerified": True,
            "accountState": "active",
            "platformAccess": "granted",
            "platformPermissions": ["core.account.get"],
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


BASE = {
    "lifecycle": "present",
    "platformAccess": "granted",
    "platformPermissions": ["core.account.get"],
    "givenName": "Ana",
    "familyName": "Souza",
    "email": "ana@example.com",
}


def test_the_view_exposes_the_generations_and_hides_internal_fields() -> None:
    view = account_view(
        record({**BASE, "campoInterno": "oculto"}, observed_generation=2)
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert (view["desiredGeneration"], view["observedGeneration"]) == (2, 2)
    assert "campoInterno" not in view["desired"]
    assert "requestedBy" not in view and "correlationId" not in view
    assert view["desired"]["email"] == "ana@example.com"


def test_a_record_without_confirmation_has_no_observed_generation() -> None:
    view = account_view(record(BASE, observed_generation=None)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert "observedGeneration" not in view


def test_a_record_without_the_protection_field_counts_as_protected() -> None:
    view = account_view(record(BASE, observed_generation=1)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert view["desired"]["deletionProtection"] is True
