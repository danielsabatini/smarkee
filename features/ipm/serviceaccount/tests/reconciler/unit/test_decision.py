"""Decisão de reconciliação da service account (ver `docs/loop/RESOURCE-CONTROL-LOOP.md`)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from ipm_serviceaccount.reconciler.domain.decision import (
    DesiredState,
    LastResult,
    ObservedState,
    PendingAction,
    ResourceState,
    action_id,
    decide,
    failure_backoff,
)
from ipm_serviceaccount.reconciler.settings import LoopSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SETTINGS = LoopSettings()
PERMISSIONS = frozenset({"ipm.serviceaccount.get", "ipm.serviceaccount.list"})
KEYS = frozenset({"a" * 64})


def desired(
    *,
    lifecycle: str = "present",
    reconciliation: str = "active",
    generation: int = 1,
    permissions: frozenset[str] = PERMISSIONS,
    keys: frozenset[str] = KEYS,
    description: str | None = None,
) -> DesiredState:
    return DesiredState(
        "d-1",
        generation,
        lifecycle,
        reconciliation,
        permissions,
        "owner-1",
        "c-1",
        deletion_protection=False,
        key_fingerprints=keys,
        description=description,
    )


def observed(
    presence: str,
    *,
    age: int = 5,
    permissions: frozenset[str] | None = PERMISSIONS,
    causation: str | None = None,
    protected: bool | None = False,
    keys: frozenset[str] = KEYS,
    description: str | None = None,
) -> ObservedState:
    return ObservedState(
        "o-1",
        presence,
        NOW - timedelta(seconds=age),
        causation,
        permissions if presence == "present" else None,
        deletion_protection=protected if presence == "present" else None,
        key_fingerprints=keys if presence == "present" else frozenset(),
        description=description,
    )


def state(d: DesiredState | None, o: ObservedState | None, **kwargs: object) -> ResourceState:
    return ResourceState(desired=d, observed=o, **kwargs)  # type: ignore[arg-type]


def operation_of(current: ResourceState) -> str | None:
    decision = decide(current, NOW, SETTINGS)
    return decision.operation if decision else None


def test_missing_serviceaccount_is_created() -> None:
    decision = decide(state(desired(), observed("absent")), NOW, SETTINGS)
    assert decision is not None
    assert (decision.operation, decision.reason) == ("create", "Missing")


def test_different_permissions_are_updated() -> None:
    extra = observed("present", permissions=PERMISSIONS | {"ipm.serviceaccount.bind"})
    assert operation_of(state(desired(), extra)) == "update"
    assert operation_of(state(desired(), observed("present", permissions=frozenset()))) == "update"
    assert operation_of(state(desired(permissions=frozenset()), observed("present"))) == "update"


def test_converged_serviceaccount_needs_no_action() -> None:
    assert operation_of(state(desired(), observed("present"))) is None
    nothing = desired(permissions=frozenset())
    assert operation_of(state(nothing, observed("present", permissions=frozenset()))) is None


def test_a_different_deletion_protection_is_drift() -> None:
    """A proteção é campo gerenciado, lida do metadado do provedor (decisão 0074)."""
    for held in (True, None):
        decision = decide(state(desired(), observed("present", protected=held)), NOW, SETTINGS)
        assert decision is not None
        assert (decision.operation, decision.reason) == ("update", "Drift")
    protected = replace(desired(), deletion_protection=True)
    assert operation_of(state(protected, observed("present", protected=True))) is None


def test_different_keys_are_drift_and_an_expired_key_is_not() -> None:
    """A chave vencida segue no `observed` como `expired`: o fingerprint existe, sem divergência."""
    other = frozenset({"b" * 64})
    variations: tuple[frozenset[str], ...] = (frozenset(), other, KEYS | other)
    for observed_keys in variations:
        decision = decide(state(desired(), observed("present", keys=observed_keys)), NOW, SETTINGS)
        assert decision is not None
        assert (decision.operation, decision.reason) == ("update", "Drift")
    assert (
        operation_of(state(desired(keys=KEYS | other), observed("present", keys=KEYS | other)))
        is None
    )


def test_a_different_description_is_drift() -> None:
    wanted = desired(description="CI deploy")
    assert operation_of(state(wanted, observed("present"))) == "update"
    assert operation_of(state(wanted, observed("present", description="CI deploy"))) is None
    assert operation_of(state(desired(), observed("present", description="antiga"))) == "update"


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
