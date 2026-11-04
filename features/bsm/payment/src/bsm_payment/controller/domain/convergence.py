"""Decisões puras do Controller sobre a observação e o resultado das ações (decisão 0096).

Mesma semântica que o Manager tinha (`docs/data/SSOT.md` §9 e §10): fase, conditions, prazo de
progresso, `ObservationStale` e limite de falhas. Recebem o estado lido do SSOT e devolvem o que
gravar; a gravação é do adaptador `store/`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bsm_payment.common.contracts import generated

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
    """Grava a condition do tipo e mantém as demais."""
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
    """Condition `Ready`; `lastTransitionAt` só muda quando o status muda."""
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
    """Condition `Progressing` da geração atual (decisão 0078)."""
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


def observation_stale(
    previous: list[dict[str, Any]],
    *,
    generation: int,
    deadline_seconds: int | None,
    now: datetime,
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Condition `ObservationStale` depois de uma observação `unknown` (decisão 0090)."""
    if deadline_seconds is None:
        return previous, False, False
    existing = _find(previous, OBSERVATION_STALE)
    if existing is not None and existing.get("status") == "True":
        return previous, True, False
    started = datetime.fromisoformat(existing["lastTransitionAt"]) if existing else now
    if now - started > timedelta(seconds=deadline_seconds):
        conditions = set_condition(
            previous,
            condition_type=OBSERVATION_STALE,
            status="True",
            reason="Timeout",
            message=f"The resource stayed unknown for more than {deadline_seconds} s.",
            generation=generation,
            now=now,
            since=now,
        )
        return conditions, True, True
    conditions = set_condition(
        previous,
        condition_type=OBSERVATION_STALE,
        status="False",
        reason="ObservationUnknown",
        message=None,
        generation=generation,
        now=now,
        since=started,
    )
    return conditions, False, False


def observation_resumed(
    previous: list[dict[str, Any]], *, generation: int, now: datetime
) -> list[dict[str, Any]]:
    """Uma observação conclusiva encerra a sequência de `unknown`."""
    existing = _find(previous, OBSERVATION_STALE)
    if existing is None:
        return previous
    if existing.get("status") != "True":
        return [c for c in previous if c.get("type") != OBSERVATION_STALE]
    return set_condition(
        previous,
        condition_type=OBSERVATION_STALE,
        status="False",
        reason="ObservationResumed",
        message=None,
        generation=generation,
        now=now,
    )


@dataclass(frozen=True, slots=True)
class ObservedDecision:
    phase: str
    conditions: list[dict[str, Any]]
    converged: bool
    remove: bool
    progress_deadline_exceeded: bool = False
    observation_stale: bool = False
    exhausted: bool = False


def decide_observed(
    is_converged: Callable[[Mapping[str, Any], str, Mapping[str, Any] | None], bool],
    *,
    desired: Mapping[str, Any],
    lifecycle: str,
    generation: int,
    observation_generation: int | None,
    presence: str,
    observed: Mapping[str, Any],
    previous_phase: str,
    previous_conditions: list[dict[str, Any]],
    now: datetime,
    progress_deadline_seconds: int | None = None,
    removes_absent: bool = True,
) -> ObservedDecision:
    """Fase, conditions e convergência depois de uma observação."""
    if presence == "unknown":
        conditions = previous_conditions or ready_condition(
            [],
            status="Unknown",
            reason="ObservationUnknown",
            message=None,
            generation=generation,
            now=now,
        )
        conditions, stale, newly_stale = observation_stale(
            conditions, generation=generation, deadline_seconds=progress_deadline_seconds, now=now
        )
        pending = stale and previous_phase != "Ready"
        return ObservedDecision(
            "Failed" if pending else previous_phase,
            conditions,
            converged=False,
            remove=False,
            observation_stale=newly_stale,
            exhausted=pending,
        )
    previous_conditions = observation_resumed(previous_conditions, generation=generation, now=now)

    converged = observation_generation == generation and is_converged(desired, presence, observed)
    if lifecycle == "absent" and converged and removes_absent:
        return ObservedDecision(previous_phase, previous_conditions, converged=True, remove=True)
    tracked = progress(
        previous_conditions,
        converged=converged,
        generation=generation,
        deadline_seconds=progress_deadline_seconds,
        now=now,
    )
    if converged:
        conditions = ready_condition(
            tracked.conditions,
            status="True",
            reason="Reconciled",
            message=None,
            generation=generation,
            now=now,
        )
        return ObservedDecision("Ready", conditions, converged=True, remove=False)
    phase = (
        "Failed"
        if previous_phase == "Failed" or tracked.exceeded
        else ("Deleting" if lifecycle == "absent" and removes_absent else "Reconciling")
    )
    conditions = ready_condition(
        tracked.conditions,
        status="False",
        reason="Failed" if phase == "Failed" else "Reconciling",
        message=None,
        generation=generation,
        now=now,
    )
    return ObservedDecision(
        phase,
        conditions,
        converged=False,
        remove=False,
        progress_deadline_exceeded=tracked.newly_exceeded,
        exhausted=tracked.exceeded,
    )


@dataclass(frozen=True, slots=True)
class ResultDecision:
    failure_count: int
    phase: str
    reconciliation: str
    conditions: list[dict[str, Any]]
    suspend: bool


def decide_result(
    *,
    failed: bool,
    failure_reason: str,
    failure_limit: int,
    generation: int,
    failure_count: int,
    phase: str,
    reconciliation: str,
    previous_conditions: list[dict[str, Any]],
    now: datetime,
) -> ResultDecision:
    """Conta a falha e suspende a reconciliação ao atingir o limite (`SSOT.md` §10.3)."""
    new_count = failure_count + (1 if failed else 0)
    suspend = failed and new_count >= failure_limit and reconciliation != "suspended"
    if phase == "Pending":
        phase = "Reconciling"
    if suspend:
        phase, reconciliation = "Failed", "suspended"
    conditions = ready_condition(
        previous_conditions,
        status="False",
        reason="FailureLimitReached" if suspend else ("ActionFailed" if failed else "Reconciling"),
        message=failure_reason if failed else None,
        generation=generation,
        now=now,
    )
    return ResultDecision(new_count, phase, reconciliation, conditions, suspend)


def check_is_converged(
    desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
) -> bool:
    if desired.get("lifecycle") == "absent":
        return presence == "absent"
    return (
        presence == "present"
        and observed is not None
        and observed.get("status") == "active"
        and observed.get("displayName") == desired.get("displayName")
        and observed.get("provider") == desired.get("provider")
        and observed.get("methodType") == desired.get("methodType")
        and bool(observed.get("providerPaymentMethodId"))
        and observed.get("deletionProtection")
        == (desired.get("deletionProtection", True) is not False)
    )
