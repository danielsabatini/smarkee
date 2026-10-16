"""Decisões puras do Manager sobre `observed` e resultados de ação (`docs/SSOT.md` §9 e §10).

Recebem o estado lido do SSOT e devolvem o que gravar; a gravação é da orquestração e do
adaptador `store/`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core_account_manager.contracts import generated
from core_account_manager.domain.policy import ResourcePolicy


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
    last_transition = now
    for existing in previous:
        if existing.get("type") == "Ready" and existing.get("status") == status:
            last_transition = datetime.fromisoformat(existing["lastTransitionAt"])
    condition = generated.Condition.model_validate(
        {
            "type": "Ready",
            "status": status,
            "reason": reason,
            **({"message": message} if message else {}),
            "observedGeneration": generation,
            "lastTransitionAt": last_transition.isoformat(),
        }
    )
    return [condition.model_dump(mode="json", exclude_none=True)]


@dataclass(frozen=True, slots=True)
class ObservedDecision:
    phase: str
    conditions: list[dict[str, Any]]
    converged: bool
    remove: bool
    """Remoção convergida: o registro sai do SSOT (`SSOT.md` §9, 8)."""


def decide_observed(
    policy: ResourcePolicy,
    *,
    desired: Mapping[str, Any],
    lifecycle: str,
    generation: int,
    presence: str,
    observed: Mapping[str, Any],
    previous_phase: str,
    previous_conditions: list[dict[str, Any]],
    now: datetime,
) -> ObservedDecision:
    if presence == "unknown":
        # Inconclusiva: registra o resultado, mas não altera a fase nem decide convergência.
        conditions = previous_conditions or ready_condition(
            [],
            status="Unknown",
            reason="ObservationUnknown",
            message=None,
            generation=generation,
            now=now,
        )
        return ObservedDecision(previous_phase, conditions, converged=False, remove=False)

    converged = policy.is_converged(desired, presence, observed)
    if lifecycle == "absent" and converged:
        return ObservedDecision(previous_phase, previous_conditions, converged=True, remove=True)
    if converged:
        conditions = ready_condition(
            previous_conditions,
            status="True",
            reason="Reconciled",
            message=None,
            generation=generation,
            now=now,
        )
        return ObservedDecision("Ready", conditions, converged=True, remove=False)
    phase = (
        previous_phase
        if previous_phase == "Failed"
        else ("Deleting" if lifecycle == "absent" else "Reconciling")
    )
    conditions = ready_condition(
        previous_conditions,
        status="False",
        reason="Failed" if phase == "Failed" else "Reconciling",
        message=None,
        generation=generation,
        now=now,
    )
    return ObservedDecision(phase, conditions, converged=False, remove=False)


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
        phase = "Reconciling"  # há uma ação em curso: a reconciliação começou
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
