"""Decisão de reconciliação da Billing Account (`docs/RESOURCE-CONTROL-LOOP.md` e segurança)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bsm_account.reconciler.domain.decision import (
    DesiredState,
    LastResult,
    ObservedState,
    PendingAction,
    ResourceState,
    action_id,
    decide,
    failure_backoff,
)
from bsm_account.reconciler.settings import LoopSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SETTINGS = LoopSettings()
NAME = "Produção Brasil"
CURRENCY = "BRL"
CONTACTS = ("finops@acme.example",)


def desired(
    *,
    lifecycle: str = "present",
    reconciliation: str = "active",
    generation: int = 1,
    display_name: str = NAME,
    currency: str = CURRENCY,
    contacts: tuple[str, ...] = CONTACTS,
) -> DesiredState:
    return DesiredState(
        "d-1",
        generation,
        lifecycle,
        reconciliation,
        display_name,
        currency,
        contacts,
        "owner-1",
        "c-1",
    )


def observed(
    presence: str,
    *,
    age: int = 5,
    display_name: str | None = None,
    currency: str | None = None,
    contacts: tuple[str, ...] = CONTACTS,
    causation: str | None = None,
    protected: bool | None = True,
) -> ObservedState:
    held_name = (
        display_name if display_name is not None else (NAME if presence == "present" else None)
    )
    held_currency = (
        currency if currency is not None else (CURRENCY if presence == "present" else None)
    )
    held_contacts = contacts if presence == "present" else ()
    return ObservedState(
        "o-1",
        presence,
        NOW - timedelta(seconds=age),
        causation,
        held_name,
        held_currency,
        held_contacts,
        deletion_protection=protected,
    )


def state(d: DesiredState | None, o: ObservedState | None, **kwargs: object) -> ResourceState:
    return ResourceState(desired=d, observed=o, **kwargs)  # type: ignore[arg-type]


def operation_of(current: ResourceState) -> str | None:
    decision = decide(current, NOW, SETTINGS)
    return decision.operation if decision else None


def test_missing_account_is_created() -> None:
    decision = decide(state(desired(), observed("absent")), NOW, SETTINGS)
    assert decision is not None
    assert (decision.operation, decision.reason) == ("create", "Missing")


def test_a_different_display_name_is_updated() -> None:
    assert operation_of(state(desired(), observed("present", display_name="Outro"))) == "update"


def test_different_contacts_are_updated() -> None:
    assert (
        operation_of(state(desired(), observed("present", contacts=("outro@acme.example",))))
        == "update"
    )


def test_a_different_currency_is_updated() -> None:
    assert operation_of(state(desired(), observed("present", currency="USD"))) == "update"


def test_converged_account_needs_no_action() -> None:
    assert operation_of(state(desired(), observed("present"))) is None


def test_a_different_deletion_protection_is_drift() -> None:
    """A proteção é campo gerenciado (decisão 0074)."""
    for held in (False, None):
        decision = decide(state(desired(), observed("present", protected=held)), NOW, SETTINGS)
        assert decision is not None
        assert (decision.operation, decision.reason) == ("update", "Drift")
    unprotected = replace(desired(), deletion_protection=False)
    converged = observed("present", protected=False)
    assert operation_of(state(unprotected, converged)) is None


def test_removal_deletes_while_present_and_converges_when_absent() -> None:
    assert operation_of(state(desired(lifecycle="absent"), observed("present"))) == "delete"
    assert operation_of(state(desired(lifecycle="absent"), observed("absent"))) is None


@pytest.mark.parametrize("missing", ["desired", "observed"])
def test_it_never_decides_without_both_states(missing: str) -> None:
    current = state(
        None if missing == "desired" else desired(),
        None if missing == "observed" else observed("absent"),
    )
    assert operation_of(current) is None


def test_suspended_reconciliation_is_never_decided() -> None:
    assert operation_of(state(desired(reconciliation="suspended"), observed("absent"))) is None


def test_unknown_observation_never_authorizes_an_action() -> None:
    assert operation_of(state(desired(), observed("unknown"))) is None


def test_stale_observation_does_not_decide_and_deletes_need_a_fresher_one() -> None:
    assert operation_of(state(desired(), observed("absent", age=601))) is None
    assert operation_of(state(desired(), observed("absent", age=599))) == "create"
    stale_for_delete = state(desired(lifecycle="absent"), observed("present", age=400))
    assert operation_of(stale_for_delete) is None  # 400 s > 300 s (metade da validade)


def test_a_pending_action_is_not_reissued_until_its_deadline() -> None:
    pending = PendingAction("a-1", 1, NOW - timedelta(seconds=30))
    assert operation_of(state(desired(), observed("absent"), pending=pending)) is None
    expired = PendingAction("a-1", 1, NOW - timedelta(seconds=121))
    assert operation_of(state(desired(), observed("absent"), pending=expired)) == "create"


def test_a_pending_action_of_another_generation_does_not_block() -> None:
    pending = PendingAction("a-1", 1, NOW - timedelta(seconds=1))
    assert (
        operation_of(state(desired(generation=2), observed("absent"), pending=pending)) == "create"
    )


def test_it_waits_for_the_observation_caused_by_the_result() -> None:
    result = LastResult("r-1", False, 1, NOW - timedelta(seconds=10))
    waiting = state(
        desired(), observed("absent"), last_result=result, awaiting_observation_of="r-1"
    )
    assert operation_of(waiting) is None
    caused = state(
        desired(),
        observed("absent", causation="r-1"),
        last_result=result,
        awaiting_observation_of="r-1",
    )
    assert operation_of(caused) == "create"


def test_the_wait_for_the_caused_observation_ends_at_the_action_deadline() -> None:
    result = LastResult("r-1", False, 1, NOW - timedelta(seconds=121))
    waiting = state(
        desired(), observed("absent"), last_result=result, awaiting_observation_of="r-1"
    )
    assert operation_of(waiting) == "create"


def test_failures_back_off_exponentially_up_to_the_maximum() -> None:
    assert failure_backoff(SETTINGS, 1) == timedelta(seconds=5)
    assert failure_backoff(SETTINGS, 3) == timedelta(seconds=20)
    assert failure_backoff(SETTINGS, 30) == timedelta(seconds=300)
    failed = LastResult("r-1", True, 1, NOW - timedelta(seconds=3))
    blocked = state(desired(), observed("absent"), last_result=failed, consecutive_failures=1)
    assert operation_of(blocked) is None
    later = LastResult("r-1", True, 1, NOW - timedelta(seconds=6))
    assert (
        operation_of(
            state(desired(), observed("absent"), last_result=later, consecutive_failures=1)
        )
        == "create"
    )


def test_action_id_is_deterministic_and_changes_with_the_observation() -> None:
    first = action_id("u1", 1, "create", "obs-a")
    assert first == action_id("u1", 1, "create", "obs-a")
    assert first != action_id("u1", 1, "create", "obs-b")
    assert first == "u1.1.create.obs-a"
