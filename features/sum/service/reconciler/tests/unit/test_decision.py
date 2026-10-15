from datetime import UTC, datetime, timedelta

from sum_service_reconciler.domain.decision import (
    DesiredState,
    LastResult,
    ObservedState,
    PendingAction,
    ResourceState,
    decide,
)
from sum_service_reconciler.settings import LoopSettings

NOW = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
ROLES = frozenset({"ipm.organization.get", "ipm.organization.list"})
SETTINGS = LoopSettings()


def desired(
    lifecycle: str = "present",
    roles: frozenset[str] = ROLES,
    reconciliation: str = "active",
    generation: int = 1,
) -> DesiredState:
    return DesiredState("m-desired", generation, lifecycle, reconciliation, roles)


def observed(
    roles: frozenset[str] = frozenset(),
    presence: str = "present",
    age: timedelta = timedelta(seconds=5),
    causation: str | None = "m-desired",
) -> ObservedState:
    return ObservedState("m-observed", presence, NOW - age, causation, roles)


def state(**kwargs: object) -> ResourceState:
    return ResourceState(**kwargs)  # type: ignore[arg-type]


def test_an_active_link_without_the_roles_asks_for_an_update() -> None:
    decision = decide(state(desired=desired(), observed=observed()), NOW, SETTINGS)
    assert decision is not None and (decision.operation, decision.reason) == ("update", "Drift")


def test_an_active_link_with_the_roles_is_converged() -> None:
    assert decide(state(desired=desired(), observed=observed(ROLES)), NOW, SETTINGS) is None


def test_extra_roles_on_an_active_link_are_not_a_divergence() -> None:
    extra = observed(ROLES | {"ipm.outro.x"})
    assert decide(state(desired=desired(), observed=extra), NOW, SETTINGS) is None


def test_a_disabled_link_with_service_roles_asks_for_their_removal() -> None:
    decision = decide(
        state(desired=desired("absent", frozenset()), observed=observed(ROLES)), NOW, SETTINGS
    )
    assert decision is not None and decision.reason == "RolesRemovalRequested"


def test_a_disabled_link_without_roles_is_converged() -> None:
    assert (
        decide(state(desired=desired("absent", frozenset()), observed=observed()), NOW, SETTINGS)
        is None
    )


def test_a_suspended_reconciliation_decides_nothing() -> None:
    assert (
        decide(
            state(desired=desired(reconciliation="suspended"), observed=observed()), NOW, SETTINGS
        )
        is None
    )


def test_an_inconclusive_observation_never_authorizes_an_action() -> None:
    assert (
        decide(state(desired=desired(), observed=observed(presence="unknown")), NOW, SETTINGS)
        is None
    )


def test_a_stale_observation_decides_nothing() -> None:
    old = observed(age=timedelta(seconds=SETTINGS.observation_validity_seconds + 1))
    assert decide(state(desired=desired(), observed=old), NOW, SETTINGS) is None


def test_without_both_states_nothing_is_decided() -> None:
    assert decide(state(desired=desired()), NOW, SETTINGS) is None
    assert decide(state(observed=observed()), NOW, SETTINGS) is None


def test_a_pending_action_of_the_same_generation_is_not_emitted_again() -> None:
    pending = PendingAction("a-1", 1, NOW - timedelta(seconds=10))
    assert (
        decide(state(desired=desired(), observed=observed(), pending=pending), NOW, SETTINGS)
        is None
    )


def test_after_the_deadline_a_pending_action_can_be_emitted_again() -> None:
    late = PendingAction("a-1", 1, NOW - timedelta(seconds=SETTINGS.action_deadline_seconds + 1))
    assert (
        decide(state(desired=desired(), observed=observed(), pending=late), NOW, SETTINGS)
        is not None
    )


def test_while_waiting_for_the_observation_caused_by_a_result_nothing_is_decided() -> None:
    waiting = state(
        desired=desired(), observed=observed(causation="m-old"), awaiting_observation_of="m-result"
    )
    assert decide(waiting, NOW, SETTINGS) is None


def test_the_caused_observation_releases_the_decision() -> None:
    caused = state(
        desired=desired(),
        observed=observed(causation="m-result"),
        awaiting_observation_of="m-result",
    )
    assert decide(caused, NOW, SETTINGS) is not None


def test_a_failure_of_the_same_generation_waits_the_backoff() -> None:
    failed = LastResult("m-result", True, 1, NOW - timedelta(seconds=5))
    assert (
        decide(
            state(
                desired=desired(), observed=observed(), last_result=failed, consecutive_failures=1
            ),
            NOW,
            SETTINGS,
        )
        is None
    )
    later = LastResult("m-result", True, 1, NOW - timedelta(minutes=5))
    assert (
        decide(
            state(
                desired=desired(), observed=observed(), last_result=later, consecutive_failures=1
            ),
            NOW,
            SETTINGS,
        )
        is not None
    )
