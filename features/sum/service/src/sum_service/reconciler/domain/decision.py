"""Decisão de reconciliação de `sum.service`: função pura sobre o estado em memória.

O Reconciler decide e não executa: compara o `desired` (a ligação pedida) com o `observed` (as
roles que o usuário tem) e responde com a `action` a publicar, ou com nada
(`docs/RESOURCE-CONTROL-LOOP.md`). As guardas são as do loop do User
(`docs/RESOURCE-CONTROL-SECURITY.md` §7 e §8): não decide com `observed` inconclusivo, desatualizado
ou ausente; não decide com `desired` suspenso; não reemite uma `action` pendente; e espera o backoff
depois de uma falha.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DesiredState:
    message_id: str
    generation: int
    lifecycle: str
    reconciliation: str
    service_roles: frozenset[str]
    traceparent: str | None = None
    """Contexto de trace do `desired` (decisão 0055): a action que ele causar o herda."""


@dataclass(frozen=True, slots=True)
class ObservedState:
    message_id: str
    presence: str
    observed_at: datetime
    causation_id: str | None
    service_roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class PendingAction:
    action_id: str
    generation: int
    emitted_at: datetime


@dataclass(frozen=True, slots=True)
class LastResult:
    message_id: str
    failed: bool
    generation: int
    received_at: datetime


@dataclass(slots=True)
class ResourceState:
    """Estado do recurso na instância: último `desired` e `observed`, ação e resultado."""

    desired: DesiredState | None = None
    observed: ObservedState | None = None
    pending: PendingAction | None = None
    last_result: LastResult | None = None
    awaiting_observation_of: str | None = None
    """`messageId` do resultado cuja observação causada ainda não chegou."""

    consecutive_failures: int = 0
    ineffective_actions: int = 0
    """Ações seguidas da geração atual que concluíram (`completed`) sem a observação causada por
    elas convergir. Entram no mesmo backoff das falhas: uma ação que não muda nada não pode se
    repetir sem freio (decisão 0078)."""
    failure_generation: int = 0


@dataclass(frozen=True, slots=True)
class Decision:
    operation: str
    reason: str
    message: str
    fields: tuple[str, ...] = ()
    """Campos gerenciados que divergem (só os nomes, nunca os valores): diagnóstico nos logs."""


class LoopParameters(Protocol):
    """Parâmetros do loop que a decisão lê (vêm de `x-resourceParameters` do `desired`)."""

    @property
    def observation_validity_seconds(self) -> int: ...

    @property
    def action_deadline_seconds(self) -> int: ...

    @property
    def failure_backoff_seconds(self) -> int: ...

    @property
    def failure_backoff_maximum_seconds(self) -> int: ...


def failure_backoff(settings: LoopParameters, failures: int) -> timedelta:
    seconds = settings.failure_backoff_seconds * (2 ** max(0, failures - 1))
    return timedelta(seconds=min(seconds, settings.failure_backoff_maximum_seconds))


def decide(state: ResourceState, now: datetime, settings: LoopParameters) -> Decision | None:
    desired, observed = state.desired, state.observed
    if desired is None or observed is None:
        return None  # sem os dois estados, não decide
    if desired.reconciliation == "suspended":
        return None
    if observed.presence == "unknown":
        return None  # observação inconclusiva nunca autoriza ação
    decision = _compare(desired, observed)
    if decision is None:
        return None  # convergido
    if now - observed.observed_at > timedelta(seconds=settings.observation_validity_seconds):
        return None  # observação desatualizada

    deadline = timedelta(seconds=settings.action_deadline_seconds)
    if state.awaiting_observation_of is not None:
        caused = observed.causation_id == state.awaiting_observation_of
        waited = state.last_result is not None and now - state.last_result.received_at > deadline
        if not caused and not waited:
            return None  # ainda sem a observação causada pelo resultado
    pending = state.pending
    if (
        pending is not None
        and pending.generation == desired.generation
        and now - pending.emitted_at < deadline
    ):
        return None  # ação pendente: não reemite
    result = state.last_result
    repeated = max(state.consecutive_failures, state.ineffective_actions)
    if (
        result is not None
        and (result.failed or state.ineffective_actions)
        and result.generation == desired.generation
        and now - result.received_at < failure_backoff(settings, repeated)
    ):
        return None  # backoff após falha ou após ação sem efeito
    return decision


def _compare(desired: DesiredState, observed: ObservedState) -> Decision | None:
    """Ligação ativa: o usuário precisa ter as roles do serviço. Desligada: não pode ter nenhuma.

    Roles a mais, além das pedidas, não são divergência para a ligação ativa. Para a desligada,
    qualquer role do serviço presente é divergência.
    """
    if desired.lifecycle == "absent":
        if observed.service_roles:
            return Decision(
                "update",
                "RolesRemovalRequested",
                "The service roles must be revoked.",
                ("serviceRoles",),
            )
        return None
    if not desired.service_roles <= observed.service_roles:
        return Decision("update", "Drift", "The user lacks the service roles.", ("serviceRoles",))
    return None


def drift(desired: DesiredState, observed: ObservedState) -> Decision | None:
    """A divergência entre o `desired` e o `observed`, sem as guardas do loop (`decide`)."""
    if observed.presence == "unknown":
        return None
    return _compare(desired, observed)


def action_id(resource_id: str, generation: int, operation: str, observed_message_id: str) -> str:
    """Identidade determinística da decisão (`docs/RESOURCE-CONTROL-LOOP.md` §14.1)."""
    return f"{resource_id}.{generation}.{operation}.{observed_message_id}"
