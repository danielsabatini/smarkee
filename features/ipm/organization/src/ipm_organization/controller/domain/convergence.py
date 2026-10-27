"""Decisões puras do Controller sobre convergência de observações (decisão 0096).

Avalia presença e divergência, calculando as conditions (`Ready`, `Progressing`,
`ObservationStale`) e a fase do recurso (`Active`, `Failed`, `Pending`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ipm_organization.common import user_access
from ipm_organization.common.contracts import generated

READY = "Ready"
PROGRESSING = "Progressing"
OBSERVATION_STALE = "ObservationStale"


def _find(conditions: list[dict[str, Any]], condition_type: str) -> dict[str, Any] | None:
    return next((c for c in conditions if c.get("type") == condition_type), None)


def set_condition(
    previous: list[dict[str, Any]],
    *,
    condition_type: str,
    status: str,
    reason: str,
    message: str | None,
    generation: int,
    now: datetime,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    last_transition = since or now
    existing = _find(previous, condition_type)
    if since is None and existing is not None and existing.get("status") == status:
        last_transition = datetime.fromisoformat(existing["lastTransitionAt"])
    condition = generated.Condition.model_validate(
        {
            "type": condition_type,
            "status": status,
            "reason": reason,
            **({"message": message} if message else {}),
            "observedGeneration": generation,
            "lastTransitionAt": last_transition.isoformat(),
        }
    )
    others = [c for c in previous if c.get("type") != condition_type]
    return [condition.model_dump(mode="json", exclude_none=True), *others]


def ready_condition(
    previous: list[dict[str, Any]],
    *,
    status: str,
    reason: str,
    message: str | None,
    generation: int,
    now: datetime,
) -> list[dict[str, Any]]:
    return set_condition(
        previous,
        condition_type=READY,
        status=status,
        reason=reason,
        message=message,
        generation=generation,
        now=now,
    )


@dataclass(frozen=True, slots=True)
class Progress:
    conditions: list[dict[str, Any]]
    exceeded: bool
    newly_exceeded: bool


def progress(
    previous: list[dict[str, Any]],
    *,
    converged: bool,
    generation: int,
    deadline_seconds: int | None,
    now: datetime,
) -> Progress:
    if deadline_seconds is None:
        return Progress(previous, exceeded=False, newly_exceeded=False)
    existing = _find(previous, PROGRESSING)
    same_generation = existing is not None and existing.get("observedGeneration") == generation
    if converged:
        conditions = set_condition(
            previous,
            condition_type=PROGRESSING,
            status="True",
            reason="Converged",
            message=None,
            generation=generation,
            now=now,
        )
        return Progress(conditions, exceeded=False, newly_exceeded=False)
    if existing is not None and same_generation and existing.get("status") == "False":
        return Progress(previous, exceeded=True, newly_exceeded=False)
    in_progress = (
        existing is not None
        and same_generation
        and existing.get("status") == "True"
        and existing.get("reason") == "Reconciling"
    )
    started = (
        datetime.fromisoformat(existing["lastTransitionAt"]) if in_progress and existing else now
    )
    if now - started > timedelta(seconds=deadline_seconds):
        conditions = set_condition(
            previous,
            condition_type=PROGRESSING,
            status="False",
            reason="ProgressDeadlineExceeded",
            message=f"The resource did not converge within {deadline_seconds} s.",
            generation=generation,
            now=now,
            since=now,
        )
        return Progress(conditions, exceeded=True, newly_exceeded=True)
    conditions = set_condition(
        previous,
        condition_type=PROGRESSING,
        status="True",
        reason="Reconciling",
        message=None,
        generation=generation,
        now=now,
        since=started,
    )
    return Progress(conditions, exceeded=False, newly_exceeded=False)


@dataclass(frozen=True, slots=True)
class ConvergenceDecision:
    phase: str
    converged: bool
    observed_generation: int | None
    conditions: list[dict[str, Any]]
    progress_exceeded: bool = False
    observation_stale_exceeded: bool = False


def check_is_converged(
    desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
) -> bool:
    if desired.get("lifecycle") == "absent":
        return presence == "absent"
    return (
        presence == "present"
        and observed is not None
        and observed.get("name") == desired.get("name")
        and observed.get("platformAccess") == desired.get("platformAccess")
        and observed.get("deletionProtection")
        == (desired.get("deletionProtection", True) is not False)
        and (
            not user_access.is_managed(desired)
            or user_access.converged(desired.get("userAccess") or {}, observed.get("userAccess"))
        )
    )


def decide_convergence(
    *,
    desired: Mapping[str, Any],
    lifecycle: str,
    generation: int,
    presence: str,
    observed: Mapping[str, Any] | None,
    previous_phase: str,
    previous_conditions: list[dict[str, Any]],
    now: datetime,
    progress_deadline_seconds: int = 300,
) -> ConvergenceDecision:
    converged = check_is_converged(desired, presence, observed)
    prog = progress(
        previous_conditions,
        converged=converged,
        generation=generation,
        deadline_seconds=progress_deadline_seconds,
        now=now,
    )
    conditions = prog.conditions

    if converged:
        ready_reason = "Converged"
        phase = "Active" if lifecycle == "present" else "Pending"
        conditions = ready_condition(
            conditions,
            status="True",
            reason=ready_reason,
            message=None,
            generation=generation,
            now=now,
        )
        return ConvergenceDecision(
            phase=phase,
            converged=True,
            observed_generation=generation,
            conditions=conditions,
        )

    # Não convergiu
    reason = "ProgressDeadlineExceeded" if prog.exceeded else "Reconciling"
    phase = "Failed" if prog.exceeded else "Pending"
    conditions = ready_condition(
        conditions,
        status="False",
        reason=reason,
        message=None,
        generation=generation,
        now=now,
    )
    return ConvergenceDecision(
        phase=phase,
        converged=False,
        observed_generation=None,
        conditions=conditions,
        progress_exceeded=prog.exceeded,
    )
