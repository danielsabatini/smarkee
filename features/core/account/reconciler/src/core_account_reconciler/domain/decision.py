"""Decisão de reconciliação da Account: função pura sobre o estado em memória.

O Reconciler decide, e não executa: compara `desired` e `observed` e responde com a `action` a
publicar, ou com nada (`docs/RESOURCE-CONTROL-LOOP.md`). A decisão respeita as regras de segurança
do loop (`docs/RESOURCE-CONTROL-SECURITY.md` §7 e §8): não decide com `observed` inconclusivo ou
desatualizado, nem com `desired` suspenso, e não reemite uma `action` pendente.
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
    platform_access: str
    platform_roles: frozenset[str]
    requested_by: str | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True)
class ObservedState:
    message_id: str
    presence: str
    observed_at: datetime
    causation_id: str | None
    platform_access: str | None
    platform_roles: frozenset[str]


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
    """Estado do recurso na instância: o último `desired` e `observed` e o andamento das ações."""

    desired: DesiredState | None = None
    observed: ObservedState | None = None
    pending: PendingAction | None = None
    last_result: LastResult | None = None
    awaiting_observation_of: str | None = None
    """`messageId` do resultado cuja observação causada ainda não chegou."""

    consecutive_failures: int = 0
    failure_generation: int = 0


@dataclass(frozen=True, slots=True)
class Decision:
    operation: str
    reason: str
    message: str


class LoopParameters(Protocol):
    """Parâmetros do loop que a decisão lê (a configuração do componente os fornece)."""

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
        return None  # sem os dois estados, não decide (§3.8)
    if desired.reconciliation == "suspended":
        return None
    if observed.presence == "unknown":
        return None  # observação inconclusiva nunca autoriza ação

    comparison = _compare(desired, observed)
    if comparison is None:
        return None  # convergido: noop
    decision = comparison

    validity = timedelta(seconds=settings.observation_validity_seconds)
    if decision.operation == "delete":
        validity /= 2  # mais estrito para ações destrutivas
    if now - observed.observed_at > validity:
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
    if (
        result is not None
        and result.failed
        and result.generation == desired.generation
        and now - result.received_at < failure_backoff(settings, state.consecutive_failures)
    ):
        return None  # backoff após falha
    return decision


def _compare(desired: DesiredState, observed: ObservedState) -> Decision | None:
    """Compara os campos gerenciados da Account: `lifecycle`, `platformAccess` e `platformRoles`.

    As roles desejadas precisam estar contidas nas observadas: roles a mais não são divergência.
    """
    if desired.lifecycle == "absent":
        if observed.presence == "present":
            return Decision("delete", "DeletionRequested", "The account must be removed.")
        return None
    if observed.presence == "absent":
        return Decision("create", "Missing", "The account does not exist in the identity provider.")
    if observed.platform_access != desired.platform_access or not (
        desired.platform_roles <= observed.platform_roles
    ):
        return Decision("update", "Drift", "The account lacks the expected platform access.")
    return None


def action_id(resource_id: str, generation: int, operation: str, observed_message_id: str) -> str:
    """Identidade determinística da decisão (`docs/RESOURCE-CONTROL-LOOP.md` §14.1)."""
    return f"{resource_id}.{generation}.{operation}.{observed_message_id}"
