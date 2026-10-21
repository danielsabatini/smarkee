"""Convergência da ligação de serviço nos handlers do template (decisões 0079 e 0080)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sum_service.manager.domain.convergence import decide_observed, decide_result
from sum_service.manager.domain.kind import SERVICE

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
ROLES = ["ipm.organization.get", "ipm.organization.list"]
ENABLED: dict[str, Any] = {
    "lifecycle": "present",
    "reconciliation": "active",
    "ownerAccountId": "01a15ec2-6db7-737f-8c03-e7df782b55c8",
    "service": "ipm",
    "serviceRoles": ROLES,
    "managedRoles": [*ROLES, "ipm.retired.role"],
}
DISABLED: dict[str, Any] = {**ENABLED, "lifecycle": "absent", "serviceRoles": []}


def observe(
    desired: dict[str, Any],
    held: list[str],
    *,
    presence: str = "present",
    phase: str = "Reconciling",
    observation_generation: int | None = 1,
    conditions: list[dict[str, Any]] | None = None,
    now: datetime = NOW,
):
    return decide_observed(
        SERVICE.policy,
        desired=desired,
        lifecycle=desired["lifecycle"],
        generation=1,
        observation_generation=observation_generation,
        presence=presence,
        observed={"serviceRoles": held},
        previous_phase=phase,
        previous_conditions=conditions or [],
        now=now,
        progress_deadline_seconds=300,
        removes_absent=SERVICE.removes_absent,
    )


def test_an_enabled_link_with_every_role_converges_to_ready() -> None:
    decision = observe(ENABLED, ROLES)
    assert decision.converged and decision.phase == "Ready" and not decision.remove


def test_a_missing_role_keeps_the_link_reconciling() -> None:
    decision = observe(ENABLED, ROLES[:1])
    assert not decision.converged and decision.phase == "Reconciling"


def test_a_leftover_managed_role_keeps_the_link_reconciling() -> None:
    """Uma role que saiu do catálogo ainda precisa ser revogada (decisão 0079)."""
    decision = observe(ENABLED, [*ROLES, "ipm.retired.role"])
    assert not decision.converged and decision.phase == "Reconciling"


def test_a_role_outside_the_link_does_not_count() -> None:
    assert observe(ENABLED, [*ROLES, "ipm.other.service"]).converged


def test_an_observation_older_than_the_generation_does_not_confirm_it() -> None:
    """Conteúdo igual não basta: a leitura precisa ser posterior à geração (decisão 0072)."""
    decision = observe(ENABLED, ROLES, observation_generation=None)
    assert not decision.converged and decision.phase == "Reconciling"


def test_a_disabled_link_converges_without_removing_the_record() -> None:
    """A ligação desfeita continua existindo (decisão 0033): `Ready`, sem apagar a linha."""
    decision = observe(DISABLED, [])
    assert decision.converged and decision.phase == "Ready" and not decision.remove
    absent_user = observe(DISABLED, [], presence="absent")
    assert absent_user.converged and not absent_user.remove


def test_a_disabled_link_still_holding_roles_reconciles_and_never_deletes() -> None:
    decision = observe(DISABLED, ["ipm.retired.role"])
    assert not decision.converged and decision.phase == "Reconciling"


def test_past_the_progress_deadline_the_link_fails() -> None:
    first = observe(ENABLED, [])
    late = observe(ENABLED, [], conditions=first.conditions, now=NOW + timedelta(seconds=301))
    progressing = next(c for c in late.conditions if c["type"] == "Progressing")
    assert (progressing["status"], progressing["reason"]) == ("False", "ProgressDeadlineExceeded")
    assert late.phase == "Failed" and late.progress_deadline_exceeded


def test_the_failure_limit_suspends_the_link() -> None:
    decision = decide_result(
        failed=True,
        failure_reason="Rejected",
        failure_limit=5,
        generation=1,
        failure_count=4,
        phase="Reconciling",
        reconciliation="active",
        previous_conditions=[],
        now=NOW,
    )
    assert decision.suspend and decision.phase == "Failed"


def test_the_desired_message_carries_the_current_reconciliation() -> None:
    data = SERVICE.policy.message_data(ENABLED, "suspended")
    assert data["reconciliation"] == "suspended" and data["managedRoles"] == ENABLED["managedRoles"]
