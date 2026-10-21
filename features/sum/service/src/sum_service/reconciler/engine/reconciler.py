"""Motor do Reconciler de `sum.service`: lê `desired`, `observed` e resultados, decide e publica.

O Reconciler decide e não executa (`docs/RESOURCE-CONTROL-LOOP.md`). A `action` vai para o subject
`reconciler.action.sum.service.<resourceId>.<operation>`, com `Nats-Msg-Id` igual ao `actionId`,
para que o transporte deduplique reemissões. A decisão é a de `domain/decision.py`.
"""

import asyncio
import logging
import random
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sum_service.common.contracts import generated
from sum_service.common.contracts.envelope import EnvelopeError, read_envelope
from sum_service.common.ids import new_identifier, utc_now
from sum_service.common.logging_config import (
    bind_context,
    bind_traceparent,
    current_traceparent,
    restore_context,
    save_context,
)
from sum_service.common.ports import Publisher, PublishError
from sum_service.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION
from sum_service.reconciler.domain.decision import (
    DesiredState,
    LastResult,
    ObservedState,
    PendingAction,
    ResourceState,
    action_id,
    decide,
    drift,
)
from sum_service.reconciler.settings import LoopSettings

logger = logging.getLogger(__name__)


class Reconciler:
    def __init__(
        self,
        publisher: Publisher,
        settings: LoopSettings,
        *,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._publisher = publisher
        self._settings = settings
        self._clock = clock
        self._identifiers = identifiers
        self._states: dict[str, ResourceState] = {}

    @property
    def resource_ids(self) -> list[str]:
        return list(self._states)

    def state_of(self, resource_id: str) -> ResourceState | None:
        return self._states.get(resource_id)

    async def on_message(self, data: bytes) -> str | None:
        """Atualiza o estado com uma mensagem e reavalia o recurso. Devolve o `resourceId`."""
        envelope = self._parse(data)
        if envelope is None:
            return None
        state = self._states.setdefault(envelope.resource_id, ResourceState())
        match envelope.message_type.value:
            case "desired":
                self._on_desired(state, envelope)
            case "observed":
                self._on_observed(state, envelope)
            case "completed" | "failed":
                self._on_result(state, envelope)
            case _:
                return None
        await self.evaluate(envelope.resource_id)
        return envelope.resource_id

    @staticmethod
    def _parse(data: bytes) -> generated.MessageEnvelope | None:
        try:
            envelope = read_envelope(data)
        except EnvelopeError as error:
            logger.error("message rejected", extra={"smarkee.reason": error.reason})
            return None
        if envelope.module != MODULE or envelope.resource_type != RESOURCE_TYPE:
            return None
        return envelope

    @staticmethod
    def _on_desired(state: ResourceState, envelope: generated.MessageEnvelope) -> None:
        generation = envelope.desired_generation
        if generation is None:
            return
        current = state.desired
        if current is not None and generation < current.generation:
            return  # geração mais antiga: ignorada
        data: Mapping[str, Any] = envelope.data
        state.desired = DesiredState(
            message_id=envelope.message_id,
            generation=generation,
            lifecycle=str(data.get("lifecycle", "present")),
            reconciliation=str(data.get("reconciliation", "active")),
            service_roles=frozenset(str(role) for role in data.get("serviceRoles", ())),
            traceparent=current_traceparent(),
            managed_roles=frozenset(
                str(role) for role in data.get("managedRoles", data.get("serviceRoles", ()))
            ),
        )
        if current is None or generation != current.generation:
            state.pending = None  # a ação pendente era de uma especificação substituída
            state.ineffective_actions = 0
            state.consecutive_failures = 0

    @staticmethod
    def _on_observed(state: ResourceState, envelope: generated.MessageEnvelope) -> None:
        if envelope.presence is None or envelope.observed_at is None:
            return
        current = state.observed
        if current is not None and envelope.observed_at <= current.observed_at:
            return  # observação não mais recente
        data: Mapping[str, Any] = envelope.data
        state.observed = ObservedState(
            message_id=envelope.message_id,
            presence=envelope.presence.value,
            observed_at=envelope.observed_at,
            causation_id=envelope.causation_id,
            service_roles=frozenset(str(role) for role in data.get("serviceRoles", ())),
        )
        if (
            state.awaiting_observation_of is not None
            and envelope.causation_id == state.awaiting_observation_of
        ):
            state.awaiting_observation_of = None  # a observação causada chegou
            Reconciler._count_effect(state, envelope.resource_id)

    def _on_result(self, state: ResourceState, envelope: generated.MessageEnvelope) -> None:
        generation = envelope.desired_generation
        if envelope.action_id is None or generation is None:
            return
        failed = envelope.message_type.value == "failed"
        if state.pending is not None and state.pending.action_id == envelope.action_id:
            state.pending = None
        state.last_result = LastResult(
            message_id=envelope.message_id,
            failed=failed,
            generation=generation,
            received_at=self._clock(),
        )
        state.awaiting_observation_of = envelope.message_id
        if failed:
            same = state.failure_generation == generation
            state.consecutive_failures = state.consecutive_failures + 1 if same else 1
            state.failure_generation = generation
        else:
            state.consecutive_failures = 0

    @staticmethod
    def _count_effect(state: ResourceState, resource_id: str) -> None:
        """Depois da observação causada por um `completed`: a ação teve efeito?

        Se o recurso ainda diverge, a ação concluiu sem mudar o que importa (por exemplo, o
        Executor e o Observer com configurações diferentes): conta como sem efeito e registra um
        aviso com os campos divergentes (decisão 0078).
        """
        result, desired, observed = state.last_result, state.desired, state.observed
        if result is None or result.failed or desired is None or observed is None:
            return
        if result.generation != desired.generation:
            return
        divergence = drift(desired, observed)
        if divergence is None:
            state.ineffective_actions = 0
            return
        state.ineffective_actions += 1
        logger.warning(
            "action had no effect",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.operation.name": divergence.operation,
                "smarkee.reason": divergence.reason,
                "smarkee.desired.generation": desired.generation,
                "smarkee.drift.fields": list(divergence.fields),
                "smarkee.action.ineffective_count": state.ineffective_actions,
            },
        )

    # ------------------------------------------------------------------ decisão

    async def evaluate_all(self) -> None:
        """Reavalia todos os recursos: validade e prazos dependem do tempo, não só de mensagens."""
        for resource_id in self.resource_ids:
            await self.evaluate(resource_id)

    async def evaluate(self, resource_id: str) -> None:
        state = self._states.get(resource_id)
        if state is None or state.desired is None:
            return
        # A action herda o trace do `desired` que a causou, mesmo quando sai de uma mensagem de
        # `observed` ou da reavaliação periódica, que não têm contexto próprio (decisão 0055).
        saved = save_context()
        bind_traceparent(state.desired.traceparent)
        bind_context(resource_id=resource_id, actor_type="system")
        try:
            await self._evaluate(resource_id, state)
        finally:
            restore_context(saved)

    async def _evaluate(self, resource_id: str, state: ResourceState) -> None:
        if state.desired is None:
            return
        now = self._clock()
        decision = decide(state, now, self._settings)
        if decision is None or state.observed is None:
            return
        desired, observed = state.desired, state.observed
        identity = action_id(
            resource_id, desired.generation, decision.operation, observed.message_id
        )
        envelope = {
            "messageId": self._identifiers(),
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "action",
            "emitter": "reconciler",
            "module": MODULE,
            "resourceType": RESOURCE_TYPE,
            "resourceId": resource_id,
            "operation": decision.operation,
            "actionId": identity,
            "desiredGeneration": desired.generation,
            "correlationId": self._identifiers(),
            "causationId": observed.message_id,
            "occurredAt": now.isoformat(),
            "publishedAt": now.isoformat(),
            "publishedBy": "sum-service-reconciler",
            "data": {"reason": decision.reason, "message": decision.message},
        }
        payload = generated.MessageEnvelope.model_validate(envelope).model_dump_json(
            exclude_none=True
        )
        subject = f"reconciler.action.{MODULE}.{RESOURCE_TYPE}.{resource_id}.{decision.operation}"
        try:
            await self._publisher.publish(subject, payload.encode(), message_id=identity)
        except PublishError:
            logger.warning("action publication failed; the decision is retried")
            return
        state.pending = PendingAction(identity, desired.generation, now)
        state.awaiting_observation_of = None
        logger.info(
            "action published",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.operation.name": decision.operation,
                "smarkee.reason": decision.reason,
                "smarkee.desired.generation": desired.generation,
                "smarkee.drift.fields": list(decision.fields),
                "smarkee.action.ineffective_count": state.ineffective_actions,
            },
        )


async def periodic_reevaluation(
    reconciler: Reconciler,
    settings: LoopSettings,
    stop: asyncio.Event,
    on_cycle: Callable[[], None] = lambda: None,
) -> None:
    """Reavalia todos os recursos de tempos em tempos, com jitter (`LOOP.md` §25)."""
    while not stop.is_set():
        on_cycle()
        jitter = 1 + random.uniform(-settings.reevaluation_jitter, settings.reevaluation_jitter)  # noqa: S311 (jitter, não criptografia)
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.reevaluation_interval_seconds * jitter
            )
        except TimeoutError:
            await reconciler.evaluate_all()
