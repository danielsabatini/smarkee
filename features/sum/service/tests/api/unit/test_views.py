"""A visão `ServiceResource` da API: só os campos do contrato, campo a campo."""

from collections.abc import Mapping
from datetime import UTC, datetime

from sum_service.api.domain.records import ResourceRecord
from sum_service.api.domain.views import service_view

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

BASE = {
    "lifecycle": "present",
    "reconciliation": "active",
    "ownerAccountId": "acc-1",
    "service": "ipm",
    "servicePermissions": ["ipm.organization.get"],
}


def record(
    desired: Mapping[str, object],
    *,
    observed_generation: int | None,
    presence: str | None = "present",
) -> ResourceRecord:
    return ResourceRecord(
        resource_id="link-1",
        resource_version=2,
        desired_generation=2,
        observed_generation=observed_generation,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired=dict(desired),
        presence=presence,
        observed={"servicePermissions": ["ipm.organization.get"]} if presence else None,
        observed_at=NOW if presence else None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_the_view_exposes_the_generations_and_hides_the_internal_ones() -> None:
    view = service_view(record(BASE, observed_generation=2)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert (view["desiredGeneration"], view["observedGeneration"]) == (2, 2)
    assert view["resourceVersion"] == "2"
    assert "requestedBy" not in view and "correlationId" not in view
    assert view["observed"]["servicePermissions"] == ["ipm.organization.get"]


def test_a_record_without_confirmation_has_no_observed_generation_nor_observed() -> None:
    view = service_view(record(BASE, observed_generation=None, presence=None)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert "observedGeneration" not in view
    assert "observed" not in view
