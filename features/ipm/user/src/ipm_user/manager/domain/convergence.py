"""Decisões puras do Manager sobre `observed` e resultados de ação (`docs/SSOT.md` §9 e §10).

Recebem o estado lido do SSOT e devolvem o que gravar; a gravação é da orquestração e do
adaptador `store/`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ipm_user.common.contracts import generated
from ipm_user.manager.domain.policy import ResourcePolicy

READY = "Ready"
PROGRESSING = "Progressing"
"""Condition de progresso, como a do Deployment do Kubernetes: `True` enquanto a geração atual está
sendo reconciliada dentro do prazo (`lastTransitionAt` marca o início da tentativa), `False` com
`ProgressDeadlineExceeded` quando o prazo passou sem convergir (decisão 0078)."""
OBSERVATION_STALE = "ObservationStale"
"""Condition de observação inconclusiva (decisão 0090): `lastTransitionAt` marca o início da
sequência de `unknown`; fica `False` (`ObservationUnknown`) dentro do prazo e `True` (`Timeout`)
quando o recurso permanece `unknown` por mais que o prazo. Some quando volta uma observação
conclusiva."""


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
    """Grava a condition do tipo e mantém as demais.

    `lastTransitionAt` é `since` quando informado; senão só muda quando o status muda.
    """
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
    """O prazo de progresso está esgotado para a geração atual."""

    newly_exceeded: bool
    """Esgotou nesta observação (para o aviso sair uma vez só)."""


def progress(
    previous: list[dict[str, Any]],
    *,
    converged: bool,
    generation: int,
    deadline_seconds: int | None,
    now: datetime,
) -> Progress:
    """Condition `Progressing` da geração atual (decisão 0078).

    A tentativa começa na primeira observação que não converge (ou numa geração nova) e termina
    quando converge. Passado o prazo sem convergir, a condition fica `False` até convergir ou até
    uma geração nova; quem limita as ações repetidas é o backoff do Reconciler.
    """
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
    """Condition `ObservationStale` depois de uma observação `unknown` (decisão 0090).

    Devolve as conditions, se o prazo está esgotado e se esgotou agora (para o aviso sair uma vez
    só). O relógio começa na primeira `unknown` da sequência e vale o `progressDeadline`.
    """
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
    """Uma observação conclusiva encerra a sequência de `unknown`: a condition sai ou, se estava
    `True`, passa a `False` (`ObservationResumed`) para registrar que o recurso voltou a ser
    lido."""
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
    """Remoção convergida: o registro sai do SSOT (`SSOT.md` §9, 8)."""

    progress_deadline_exceeded: bool = False
    """O prazo de progresso esgotou nesta observação (decisão 0078)."""

    observation_stale: bool = False
    """O recurso passou do prazo em `unknown` nesta observação (decisão 0090)."""

    exhausted: bool = False
    """A geração com trabalho pendente esgotou o prazo (de progresso ou de observação): a
    Operation vira `failed`, como no `failureLimit`. Sai sozinho da fase `Failed` ao convergir."""


def decide_observed(
    policy: ResourcePolicy,
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
    """Fase, conditions e convergência depois de uma observação.

    `removes_absent` diz se o tipo apaga o registro quando a remoção converge (o padrão) ou o
    mantém, como a ligação desfeita do `sum.service`, que segue existindo (decisão 0033). Quem
    mantém o registro não passa por `Deleting`: enquanto não converge, fica em `Reconciling`.
    """
    if presence == "unknown":
        # Inconclusiva: registra o resultado e não decide convergência. Além do prazo em `unknown`
        # (decisão 0090), um recurso com trabalho pendente vai a `Failed`: sem isso uma exclusão
        # que o Observer nunca consegue ler ficaria em `Deleting` para sempre.
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

    # Converge só com o conteúdo igual **e** com uma observação feita depois da geração vigente
    # (o Observer informa a geração que conhecia antes de ler o provedor). Uma leitura anterior à
    # geração não a confirma, mesmo com o conteúdo igual: é o caso de uma alteração só em campo da
    # plataforma, que o provedor não tem (decisão 0072).
    converged = observation_generation == generation and policy.is_converged(
        desired, presence, observed
    )
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
    # Prazo de progresso esgotado é falha visível, como a de limite de falhas (decisão 0078).
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
