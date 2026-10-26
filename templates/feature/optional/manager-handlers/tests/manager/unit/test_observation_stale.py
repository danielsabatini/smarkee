"""`unknown` além do prazo: `ObservationStale`, `Failed` e Operation `failed` (decisão 0090)."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from @@PACKAGE@@.manager.domain.convergence import decide_observed

START = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
DEADLINE = 300
DESIRED = {"lifecycle": "present"}


class SamePolicy:
    """Converge quando o recurso está presente; o resto da política não importa aqui."""

    def is_converged(self, desired: Mapping[str, Any], presence: str, observed: Any) -> bool:
        return presence == "present"


def observe(
    presence: str,
    *,
    at: int,
    phase: str,
    conditions: list[dict[str, Any]],
    lifecycle: str = "present",
):
    return decide_observed(
        SamePolicy(),  # pyright: ignore[reportArgumentType]
        desired=DESIRED,
        lifecycle=lifecycle,
        generation=1,
        observation_generation=1,
        presence=presence,
        observed={},
        previous_phase=phase,
        previous_conditions=conditions,
        now=START + timedelta(seconds=at),
        progress_deadline_seconds=DEADLINE,
    )


def stale(conditions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((c for c in conditions if c["type"] == "ObservationStale"), None)


def test_unknown_within_the_deadline_marks_the_start_and_keeps_the_phase() -> None:
    first = observe("unknown", at=0, phase="Deleting", conditions=[], lifecycle="absent")
    later = observe("unknown", at=200, phase="Deleting", conditions=first.conditions)
    condition = stale(later.conditions)
    assert condition and condition["status"] == "False"
    assert datetime.fromisoformat(condition["lastTransitionAt"]) == START
    assert later.phase == "Deleting" and not later.exhausted and not later.observation_stale


def test_unknown_past_the_deadline_fails_once_and_keeps_failing() -> None:
    first = observe("unknown", at=0, phase="Deleting", conditions=[], lifecycle="absent")
    late = observe("unknown", at=400, phase="Deleting", conditions=first.conditions)
    condition = stale(late.conditions)
    assert condition and condition["status"] == "True" and condition["reason"] == "Timeout"
    assert late.phase == "Failed" and late.exhausted and late.observation_stale
    again = observe("unknown", at=500, phase="Failed", conditions=late.conditions)
    assert again.phase == "Failed" and again.exhausted and not again.observation_stale


def test_a_ready_resource_that_turns_unknown_keeps_ready() -> None:
    first = observe("unknown", at=0, phase="Ready", conditions=[])
    late = observe("unknown", at=400, phase="Ready", conditions=first.conditions)
    assert late.phase == "Ready" and not late.exhausted
    assert stale(late.conditions)["status"] == "True"  # pyright: ignore[reportOptionalSubscript]


def test_a_conclusive_observation_clears_a_pending_stale_condition() -> None:
    first = observe("unknown", at=0, phase="Reconciling", conditions=[])
    back = observe("present", at=60, phase="Reconciling", conditions=first.conditions)
    assert stale(back.conditions) is None
    assert back.converged and back.phase == "Ready"


def test_a_conclusive_observation_after_the_timeout_records_the_resumption() -> None:
    first = observe("unknown", at=0, phase="Reconciling", conditions=[])
    late = observe("unknown", at=400, phase="Reconciling", conditions=first.conditions)
    back = observe("present", at=500, phase="Failed", conditions=late.conditions)
    condition = stale(back.conditions)
    assert condition and condition["status"] == "False"
    assert condition["reason"] == "ObservationResumed"
    assert back.phase == "Ready"
