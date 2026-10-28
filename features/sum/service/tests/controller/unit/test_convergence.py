"""Decisões puras sobre `observed` e resultados de ação, sem banco (decisões 0072, 0078 e 0090)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sum_service.controller.domain.convergence import (
    decide_observed,
    decide_result,
    is_service_converged,
    managed_permissions,
    permissions_of,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PERMISSIONS = ["ipm.organization.get", "ipm.organization.create"]
DESIRED_PRESENT: dict[str, Any] = {
    "lifecycle": "present",
    "ownerAccountId": "acc-1",
    "service": "ipm",
    "servicePermissions": PERMISSIONS,
    "managedPermissions": [*PERMISSIONS, "ipm.organization.delete"],
}
DESIRED_ABSENT: dict[str, Any] = {
    **DESIRED_PRESENT,
    "lifecycle": "absent",
    "servicePermissions": [],
}


def observe(
    presence: str,
    *,
    desired: dict[str, Any],
    phase: str = "Pending",
    observation_generation: int | None = 1,
    held: list[str] | None = None,
):
    return decide_observed(
        is_service_converged,
        desired=desired,
        lifecycle=desired["lifecycle"],
        generation=1,
        observation_generation=observation_generation,
        presence=presence,
        observed={"servicePermissions": PERMISSIONS if held is None else held},
        previous_phase=phase,
        previous_conditions=[],
        now=NOW,
        removes_absent=False,
    )


def test_present_and_matching_converges_to_ready() -> None:
    decision = observe("present", desired=DESIRED_PRESENT)
    assert decision.converged and decision.phase == "Ready" and not decision.remove


def test_missing_a_desired_permission_keeps_reconciling() -> None:
    decision = observe("present", desired=DESIRED_PRESENT, held=PERMISSIONS[:1])
    assert not decision.converged and decision.phase == "Reconciling"


def test_a_managed_permission_that_is_no_longer_wanted_keeps_reconciling() -> None:
    desired = {**DESIRED_PRESENT, "servicePermissions": PERMISSIONS[:1]}
    decision = observe("present", desired=desired, held=PERMISSIONS)
    assert not decision.converged and decision.phase == "Reconciling"


def test_permissions_outside_the_managed_ones_are_ignored() -> None:
    decision = observe("present", desired=DESIRED_PRESENT, held=[*PERMISSIONS, "bsm.account.get"])
    assert decision.converged


def test_failed_phase_is_kept_while_not_converged() -> None:
    decision = observe("present", desired=DESIRED_PRESENT, phase="Failed", held=[])
    assert decision.phase == "Failed" and decision.conditions[0]["reason"] == "Failed"


def test_a_disabled_link_converges_without_removing_the_record() -> None:
    """A ligação desfeita segue existindo (decisão 0033): converge, mas a linha não sai."""
    decision = observe("present", desired=DESIRED_ABSENT, held=[])
    assert decision.converged and decision.phase == "Ready" and not decision.remove


def test_a_disabled_link_whose_owner_no_longer_exists_converges() -> None:
    decision = observe("absent", desired=DESIRED_ABSENT, held=[])
    assert decision.converged and not decision.remove


def test_a_pending_disable_keeps_reconciling_not_deleting() -> None:
    decision = observe("present", desired=DESIRED_ABSENT, held=PERMISSIONS)
    assert not decision.converged and decision.phase == "Reconciling"


def test_an_enabled_link_of_a_missing_user_does_not_converge() -> None:
    decision = observe("absent", desired=DESIRED_PRESENT, held=[])
    assert not decision.converged and decision.phase == "Reconciling"


def test_unknown_observation_does_not_decide_convergence() -> None:
    decision = observe("unknown", desired=DESIRED_PRESENT, phase="Reconciling")
    assert not decision.converged and decision.phase == "Reconciling"
    assert decision.conditions[0]["status"] == "Unknown"


def test_observation_older_than_the_generation_does_not_converge() -> None:
    """Conteúdo igual não basta: a observação precisa ser posterior à geração (decisão 0072)."""
    decision = observe(
        "present", desired=DESIRED_PRESENT, phase="Reconciling", observation_generation=None
    )
    assert not decision.converged and decision.phase == "Reconciling"


def test_managed_permissions_default_to_the_service_permissions() -> None:
    assert managed_permissions({"servicePermissions": ["a.b.c"]}) == {"a.b.c"}
    assert managed_permissions(DESIRED_PRESENT) == {*PERMISSIONS, "ipm.organization.delete"}
    assert permissions_of(None) == frozenset()


# ---------------------------------------------------------------------- resultado das ações


def result(*, failed: bool, count: int, limit: int = 3, reconciliation: str = "active"):
    return decide_result(
        failed=failed,
        failure_reason="Rejected",
        failure_limit=limit,
        generation=1,
        failure_count=count,
        phase="Pending",
        reconciliation=reconciliation,
        previous_conditions=[],
        now=NOW,
    )


def test_failure_below_the_limit_counts_and_keeps_reconciling() -> None:
    decision = result(failed=True, count=0)
    assert decision.failure_count == 1 and decision.phase == "Reconciling"
    assert not decision.suspend


def test_failure_at_the_limit_suspends_the_reconciliation() -> None:
    decision = result(failed=True, count=2)
    assert decision.suspend and decision.phase == "Failed"
    assert decision.reconciliation == "suspended"
    assert decision.conditions[0]["reason"] == "FailureLimitReached"


def test_success_does_not_count_a_failure() -> None:
    decision = result(failed=False, count=2)
    assert decision.failure_count == 2 and not decision.suspend


def test_already_suspended_does_not_suspend_again() -> None:
    assert not result(failed=True, count=9, reconciliation="suspended").suspend


# ---------------------------------------------------------------------- prazos (0078 e 0090)


def absent_while_present(*, at: datetime, conditions: list[dict[str, Any]], generation: int = 1):
    """Uma observação que nunca converge: o recurso deveria existir e não existe."""
    return decide_observed(
        is_service_converged,
        desired=DESIRED_PRESENT,
        lifecycle="present",
        generation=generation,
        observation_generation=generation,
        presence="absent",
        observed={},
        previous_phase="Reconciling",
        previous_conditions=conditions,
        now=at,
        progress_deadline_seconds=300,
    )


def unknown(*, at: datetime, conditions: list[dict[str, Any]], phase: str = "Reconciling"):
    return decide_observed(
        is_service_converged,
        desired=DESIRED_PRESENT,
        lifecycle="present",
        generation=1,
        observation_generation=1,
        presence="unknown",
        observed={},
        previous_phase=phase,
        previous_conditions=conditions,
        now=at,
        progress_deadline_seconds=300,
    )


def condition_of(conditions: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(c for c in conditions if c["type"] == kind)


def test_progress_starts_at_the_first_divergent_observation_and_keeps_its_start() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    later = absent_while_present(at=NOW + timedelta(seconds=200), conditions=first.conditions)
    condition = condition_of(later.conditions, "Progressing")
    assert (condition["status"], condition["reason"]) == ("True", "Reconciling")
    assert datetime.fromisoformat(condition["lastTransitionAt"]) == NOW
    assert later.phase == "Reconciling" and not later.progress_deadline_exceeded


def test_past_the_deadline_the_resource_fails_once_and_stays_failed() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    late = absent_while_present(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    condition = condition_of(late.conditions, "Progressing")
    assert (condition["status"], condition["reason"]) == ("False", "ProgressDeadlineExceeded")
    assert late.phase == "Failed" and late.progress_deadline_exceeded
    again = absent_while_present(at=NOW + timedelta(seconds=400), conditions=late.conditions)
    assert again.phase == "Failed" and not again.progress_deadline_exceeded  # avisa uma vez só


def test_a_new_generation_restarts_the_progress_clock() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    late = absent_while_present(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    newer = absent_while_present(
        at=NOW + timedelta(seconds=302), conditions=late.conditions, generation=2
    )
    condition = condition_of(newer.conditions, "Progressing")
    assert (condition["status"], condition["reason"]) == ("True", "Reconciling")
    assert datetime.fromisoformat(condition["lastTransitionAt"]) == NOW + timedelta(seconds=302)


def test_a_failure_result_keeps_the_progress_condition() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    decision = decide_result(
        failed=True,
        failure_reason="Rejected",
        failure_limit=5,
        generation=1,
        failure_count=0,
        phase="Reconciling",
        reconciliation="active",
        previous_conditions=first.conditions,
        now=NOW,
    )
    assert {c["type"] for c in decision.conditions} == {"Ready", "Progressing"}


def test_unknown_within_the_deadline_is_not_stale() -> None:
    first = unknown(at=NOW, conditions=[])
    again = unknown(at=NOW + timedelta(seconds=100), conditions=first.conditions)
    stale = condition_of(again.conditions, "ObservationStale")
    assert (stale["status"], stale["reason"]) == ("False", "ObservationUnknown")
    assert not again.observation_stale and not again.exhausted


def test_unknown_past_the_deadline_fails_the_pending_resource_once() -> None:
    first = unknown(at=NOW, conditions=[])
    late = unknown(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    stale = condition_of(late.conditions, "ObservationStale")
    assert (stale["status"], stale["reason"]) == ("True", "Timeout")
    assert late.phase == "Failed" and late.observation_stale and late.exhausted
    again = unknown(at=NOW + timedelta(seconds=400), conditions=late.conditions)
    assert not again.observation_stale  # avisa uma vez só


def test_a_ready_resource_does_not_fail_when_the_observation_goes_stale() -> None:
    first = unknown(at=NOW, conditions=[], phase="Ready")
    late = unknown(at=NOW + timedelta(seconds=301), conditions=first.conditions, phase="Ready")
    assert late.observation_stale and late.phase == "Ready" and not late.exhausted


def test_a_conclusive_observation_ends_the_stale_sequence() -> None:
    first = unknown(at=NOW, conditions=[])
    resumed = absent_while_present(at=NOW + timedelta(seconds=10), conditions=first.conditions)
    assert "ObservationStale" not in {c["type"] for c in resumed.conditions}
