"""A visão `resource` da API: só os campos do contrato da visão, campo a campo."""

from datetime import UTC, datetime

from ipm_permission.api.domain.records import ResourceRecord
from ipm_permission.api.domain.views import permission_view

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _record(*, observed_generation: int | None, with_observed: bool = True) -> ResourceRecord:
    return ResourceRecord(
        resource_id="perm-1",
        resource_version=2,
        desired_generation=2,
        observed_generation=observed_generation,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "name": "ipm.thing.get",
            "description": "Ler coisas",
            "grantable": True,
            "deletionProtection": True,
        },
        presence="present" if with_observed else None,
        observed={"name": "ipm.thing.get", "description": "Ler coisas", "group": "ipm"}
        if with_observed
        else None,
        observed_at=NOW if with_observed else None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_the_view_shows_desired_observed_and_generations() -> None:
    view = permission_view(_record(observed_generation=2)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert view["desired"]["grantable"] is True
    assert view["observed"]["group"] == "ipm"
    assert view["observedGeneration"] == 2


def test_the_view_omits_observed_and_observed_generation_before_the_first_observation() -> None:
    view = permission_view(_record(observed_generation=None, with_observed=False)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert "observed" not in view
    assert "observedGeneration" not in view
