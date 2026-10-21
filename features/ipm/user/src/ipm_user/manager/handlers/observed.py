"""Tratamento de `observed` pelo Manager (`docs/SSOT.md` §10.2).

Cada mensagem é uma unidade atômica de gravação: a linha do recurso é bloqueada antes de qualquer
leitura de estado (invariante 9), a idempotência é semântica (monotonia de `observedAt`) e a
mensagem `updated` vai para o outbox na mesma transação. A confirmação ao transporte é de quem
chama, depois do retorno (depois do `COMMIT`).

Uma geração só é confirmada (`observed_generation`) por uma observação feita depois dela: o
Observer informa no `observedGeneration` do envelope a geração que conhecia antes de ler o
provedor, como o `status.observedGeneration` do Kubernetes. A Operation conclui nessa confirmação.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from ipm_user.common.contracts import generated
from ipm_user.common.ids import new_identifier, utc_now
from ipm_user.manager.domain.convergence import decide_observed
from ipm_user.manager.domain.errors import PermanentMessageError
from ipm_user.manager.domain.kind import ResourceKind
from ipm_user.manager.domain.outcome import Outcome, OutcomeKind
from ipm_user.manager.handlers.envelope import parse_envelope
from ipm_user.manager.handlers.ports import Store
from ipm_user.manager.handlers.publishing import Publishing

logger = logging.getLogger(__name__)


class ObservedHandler:
    """Aplica um `observed` ao recurso: guarda a observação e recalcula `conditions` e `phase`."""

    def __init__(
        self,
        *,
        clock: Callable[[], Any] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
        progress_deadline_seconds: int | None = None,
    ) -> None:
        self._clock = clock
        self._progress_deadline_seconds = progress_deadline_seconds
        self._publishing = Publishing(clock, identifiers)

    async def handle(
        self, store: Store, kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> Outcome:
        envelope = parse_envelope(kind, raw_message, message_type="observed", emitter="observer")
        if envelope.presence is None or envelope.observed_at is None:
            raise PermanentMessageError("observed sem presence ou observedAt")
        async with store.transaction():
            outcome = await self._apply(store, kind, envelope)
        logger.info(
            "observed handled",
            extra={
                "smarkee.resource.id": envelope.resource_id,
                "smarkee.observation.presence": envelope.presence.value,
                "smarkee.outcome": outcome.kind.value,
            },
        )
        return outcome

    async def _apply(
        self, store: Store, kind: ResourceKind, envelope: generated.MessageEnvelope
    ) -> Outcome:
        assert envelope.presence is not None and envelope.observed_at is not None  # noqa: S101
        row = await store.lock_resource(envelope.resource_id)
        if row is None:
            return Outcome(OutcomeKind.IGNORED)
        if row["observed_at"] is not None and row["observed_at"] >= envelope.observed_at:
            return Outcome(OutcomeKind.IGNORED)  # observação não mais recente (SSOT.md §9, 5)

        generation: int = row["desired_generation"]
        lifecycle: str = row["lifecycle"]
        observed_data: dict[str, Any] = dict(envelope.data)
        decision = decide_observed(
            kind.policy,
            desired=row["desired"],
            lifecycle=lifecycle,
            generation=generation,
            observation_generation=envelope.observed_generation,
            presence=envelope.presence.value,
            observed=observed_data,
            previous_phase=row["phase"],
            previous_conditions=row["conditions"],
            now=self._clock(),
            progress_deadline_seconds=self._progress_deadline_seconds,
            removes_absent=kind.removes_absent,
        )
        if decision.progress_deadline_exceeded:
            logger.warning(
                "progress deadline exceeded",
                extra={
                    "smarkee.resource.id": envelope.resource_id,
                    "smarkee.desired.generation": generation,
                    "smarkee.progress.deadline_seconds": self._progress_deadline_seconds,
                },
            )

        if decision.remove:
            return await self._remove(store, kind, envelope, row)

        resource_version = await store.save_observation(
            envelope.resource_id,
            observed=observed_data,
            presence=envelope.presence.value,
            observed_at=envelope.observed_at,
            conditions=decision.conditions,
            phase=decision.phase,
            observed_generation=generation if decision.converged else None,
        )
        await store.settle_operations(
            envelope.resource_id, generation, converged=decision.converged
        )
        await self._publishing.updated(
            store,
            kind,
            envelope,
            lifecycle=lifecycle,
            phase=decision.phase,
            resource_version=resource_version,
            desired_generation=generation,
            observed_generation=generation if decision.converged else row["observed_generation"],
        )
        return Outcome(OutcomeKind.APPLIED)

    async def _remove(
        self,
        store: Store,
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        row: Mapping[str, Any],
    ) -> Outcome:
        """Remoção convergida: o registro sai do SSOT (`SSOT.md` §9, 8; PostgreSQL §13)."""
        await store.settle_operations(
            envelope.resource_id, row["desired_generation"], converged=True
        )
        await store.delete_resource(envelope.resource_id)
        await self._publishing.updated(
            store,
            kind,
            envelope,
            lifecycle="absent",
            phase="Deleting",
            resource_version=row["resource_version"] + 1,
            desired_generation=row["desired_generation"],
            observed_generation=row["desired_generation"],
            removed=True,
        )
        return Outcome(OutcomeKind.APPLIED)
