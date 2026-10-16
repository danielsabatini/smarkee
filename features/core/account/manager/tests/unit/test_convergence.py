"""Decisões puras sobre `observed` e resultados de ação, sem banco."""

from datetime import UTC, datetime
from typing import Any

from core_account_manager.domain.convergence import decide_observed, decide_result
from core_account_manager.domain.kind import ACCOUNT

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
ROLES = ["ipm.organization.get", "core.account.get"]
DESIRED_PRESENT = {"lifecycle": "present", "platformAccess": "granted", "platformRoles": ROLES}


def observe(presence: str, *, desired: dict[str, Any], lifecycle: str, phase: str = "Pending"):
    return decide_observed(
        ACCOUNT.policy,
        desired=desired,
        lifecycle=lifecycle,
        generation=1,
        presence=presence,
        observed={"platformAccess": "granted", "platformRoles": [*ROLES, "core.account.admin"]},
        previous_phase=phase,
        previous_conditions=[],
        now=NOW,
    )


def test_present_and_matching_converges_to_ready() -> None:
    decision = observe("present", desired=DESIRED_PRESENT, lifecycle="present")
    assert decision.converged and decision.phase == "Ready" and not decision.remove
    assert decision.conditions[0]["status"] == "True"


def test_present_but_different_keeps_reconciling() -> None:
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "platformAccess": "revoked",
        "platformRoles": [],
    }
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"


def test_failed_phase_is_kept_while_not_converged() -> None:
    desired: dict[str, Any] = {
        "lifecycle": "present",
        "platformAccess": "revoked",
        "platformRoles": [],
    }
    decision = observe("present", desired=desired, lifecycle="present", phase="Failed")
    assert decision.phase == "Failed" and decision.conditions[0]["reason"] == "Failed"


def test_absent_when_removal_is_wanted_removes_the_record() -> None:
    desired = {"lifecycle": "absent", "platformAccess": "granted", "platformRoles": ROLES}
    decision = observe("absent", desired=desired, lifecycle="absent")
    assert decision.remove and decision.converged


def test_unknown_observation_does_not_decide_convergence() -> None:
    decision = observe("unknown", desired=DESIRED_PRESENT, lifecycle="present", phase="Reconciling")
    assert not decision.converged and decision.phase == "Reconciling"
    assert decision.conditions[0]["status"] == "Unknown"


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


def test_missing_a_desired_role_keeps_reconciling() -> None:
    desired = {**DESIRED_PRESENT, "platformRoles": [*ROLES, "ipm.organization.create"]}
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"
