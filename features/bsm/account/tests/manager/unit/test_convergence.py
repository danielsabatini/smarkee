"""Decisões puras sobre `observed` e resultados de ação, sem banco."""

from datetime import UTC, datetime, timedelta
from typing import Any

from bsm_account.manager.domain.convergence import decide_observed, decide_result
from bsm_account.manager.domain.kind import ACCOUNT

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
DESIRED_PRESENT: dict[str, Any] = {
    "lifecycle": "present",
    "displayName": "Produção Brasil",
    "billingCurrency": "BRL",
    "billingContacts": ["finops@acme.example"],
    "deletionProtection": True,
    "ownerAccountId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
}


def observe(
    presence: str,
    *,
    desired: dict[str, Any],
    lifecycle: str,
    phase: str = "Pending",
    observation_generation: int | None = 1,
):
    return decide_observed(
        ACCOUNT.policy,
        desired=desired,
        lifecycle=lifecycle,
        generation=1,
        observation_generation=observation_generation,
        presence=presence,
        observed={
            "displayName": "Produção Brasil",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.example"],
            "deletionProtection": True,
        },
        previous_phase=phase,
        previous_conditions=[],
        now=NOW,
    )


def test_present_and_matching_converges_to_ready() -> None:
    decision = observe("present", desired=DESIRED_PRESENT, lifecycle="present")
    assert decision.converged and decision.phase == "Ready" and not decision.remove
    assert decision.conditions[0]["status"] == "True"


def test_present_but_different_keeps_reconciling() -> None:
    desired = {**DESIRED_PRESENT, "displayName": "Outro Nome"}
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"


def test_different_contacts_keeps_reconciling() -> None:
    desired = {**DESIRED_PRESENT, "billingContacts": ["outro@acme.example"]}
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"


def test_failed_phase_is_kept_while_not_converged() -> None:
    desired = {**DESIRED_PRESENT, "displayName": "Outro Nome"}
    decision = observe("present", desired=desired, lifecycle="present", phase="Failed")
    assert decision.phase == "Failed" and decision.conditions[0]["reason"] == "Failed"


def test_absent_when_removal_is_wanted_removes_the_record() -> None:
    desired = {**DESIRED_PRESENT, "lifecycle": "absent"}
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


def test_the_owner_is_not_a_managed_field() -> None:
    desired = {**DESIRED_PRESENT, "ownerAccountId": "0199c8a4-0000-7000-8000-00000000beef"}
    decision = observe("present", desired=desired, lifecycle="present")
    assert decision.converged


def test_observation_older_than_the_generation_does_not_converge() -> None:
    """Conteúdo igual não basta: a observação precisa ser posterior à geração (decisão 0072)."""
    decision = observe(
        "present",
        desired=DESIRED_PRESENT,
        lifecycle="present",
        phase="Reconciling",
        observation_generation=None,
    )
    assert not decision.converged and decision.phase == "Reconciling"


def test_removal_needs_an_observation_of_the_removal_generation() -> None:
    desired = {**DESIRED_PRESENT, "lifecycle": "absent"}
    decision = observe(
        "absent", desired=desired, lifecycle="absent", phase="Deleting", observation_generation=None
    )
    assert not decision.converged and not decision.remove


def test_a_different_deletion_protection_keeps_reconciling() -> None:
    """A proteção é campo gerenciado: o estado observado precisa bater (decisão 0074)."""
    unprotected = {**DESIRED_PRESENT, "deletionProtection": False}
    decision = observe("present", desired=unprotected, lifecycle="present", phase="Reconciling")
    assert not decision.converged and decision.phase == "Reconciling"


def test_policy_parse_and_message_data() -> None:
    import pytest

    from bsm_account.manager.domain.errors import PermanentMessageError

    create_req = ACCOUNT.policy.parse(
        "create",
        {
            "operationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
            "requestDigest": "d" * 64,
            "specification": {
                "displayName": "Produção Brasil",
                "billingCurrency": "BRL",
                "billingContacts": ["finops@acme.example"],
            },
        },
    )
    assert create_req.operation == "create"
    assert create_req.specification == {
        "displayName": "Produção Brasil",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.example"],
    }

    update_req = ACCOUNT.policy.parse(
        "update",
        {
            "operationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
            "requestDigest": "d" * 64,
            "resourceVersion": "3",
            "specification": {
                "displayName": "Novo",
                "billingContacts": ["novo@acme.example"],
                "deletionProtection": False,
            },
            "reconciliation": "suspended",
        },
    )
    assert update_req.resource_version == 3
    assert update_req.reconciliation == "suspended"
    assert update_req.specification == {
        "displayName": "Novo",
        "billingContacts": ["novo@acme.example"],
        "deletionProtection": False,
    }

    delete_req = ACCOUNT.policy.parse(
        "delete",
        {
            "operationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
            "requestDigest": "d" * 64,
            "resourceVersion": "3",
        },
    )
    assert delete_req.resource_version == 3

    msg_data = ACCOUNT.policy.message_data(DESIRED_PRESENT, "active")
    assert msg_data["reconciliation"] == "active"
    assert msg_data["billingCurrency"] == "BRL"

    with pytest.raises(PermanentMessageError):
        ACCOUNT.policy.parse("reconcile", {})

    with pytest.raises(PermanentMessageError):
        ACCOUNT.policy.parse("delete", {"operationId": "bad", "requestDigest": "x"})

    with pytest.raises(PermanentMessageError):
        ACCOUNT.policy.parse(
            "create",
            {
                "operationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
                "requestDigest": "d" * 64,
                "specification": {
                    "displayName": "Produção Brasil",
                    "billingCurrency": "BRL",
                    "billingContacts": ["finops@acme.example", "finops@acme.example"],
                },
            },
        )


def test_policy_unique_value_and_desired_helpers() -> None:
    from bsm_account.manager.domain.policy import Request, UniqueValue

    assert ACCOUNT.policy.unique_value(DESIRED_PRESENT) == UniqueValue(
        field="displayName",
        value="Produção Brasil",
        owner="0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
        lock_key="bsm.account.display_name:0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e:Produção Brasil",
    )
    assert ACCOUNT.policy.unique_value({**DESIRED_PRESENT, "lifecycle": "absent"}) is None
    req_create = Request(
        "create",
        "op-1",
        "d" * 64,
        specification={
            "displayName": "Teste",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.example"],
        },
    )
    assert ACCOUNT.policy.desired_for_create(req_create, requested_by="ana") == {
        "lifecycle": "present",
        "displayName": "Teste",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.example"],
        "deletionProtection": True,
        "ownerAccountId": "ana",
    }
    req_update = Request("update", "op-2", "d" * 64, specification={"displayName": "Novo"})
    assert ACCOUNT.policy.desired_for_update(DESIRED_PRESENT, req_update)["displayName"] == "Novo"
    assert ACCOUNT.policy.desired_for_delete(DESIRED_PRESENT)["lifecycle"] == "absent"
    assert not ACCOUNT.policy.invalid(DESIRED_PRESENT)
    assert ACCOUNT.policy.invalid({**DESIRED_PRESENT, "billingContacts": ["a@b.co", "a@b.co"]})


def absent_while_present(*, at: datetime, conditions: list[dict[str, Any]], generation: int = 1):
    """Uma observação que nunca converge: o recurso deveria existir e não existe."""
    return decide_observed(
        ACCOUNT.policy,
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


def progressing(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return next(c for c in conditions if c["type"] == "Progressing")


def test_progress_starts_at_the_first_divergent_observation_and_keeps_its_start() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    later = absent_while_present(at=NOW + timedelta(seconds=200), conditions=first.conditions)
    condition = progressing(later.conditions)
    assert (condition["status"], condition["reason"]) == ("True", "Reconciling")
    assert datetime.fromisoformat(condition["lastTransitionAt"]) == NOW
    assert later.phase == "Reconciling" and not later.progress_deadline_exceeded
    assert {c["type"] for c in later.conditions} == {"Ready", "Progressing"}


def test_past_the_deadline_the_resource_fails_once_and_stays_failed() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    late = absent_while_present(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    condition = progressing(late.conditions)
    assert (condition["status"], condition["reason"]) == ("False", "ProgressDeadlineExceeded")
    assert late.phase == "Failed" and late.progress_deadline_exceeded
    again = absent_while_present(at=NOW + timedelta(seconds=400), conditions=late.conditions)
    assert again.phase == "Failed" and not again.progress_deadline_exceeded


def test_a_new_generation_restarts_the_progress_clock() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    late = absent_while_present(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    newer = absent_while_present(
        at=NOW + timedelta(seconds=302), conditions=late.conditions, generation=2
    )
    condition = progressing(newer.conditions)
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
