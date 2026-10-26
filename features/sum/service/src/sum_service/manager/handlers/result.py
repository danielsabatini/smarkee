"""Tratamento de `completed` e `failed` de uma ação pelo Manager (`docs/data/SSOT.md` §10.3).

Conta as falhas por geração e suspende a reconciliação no limite. A idempotência é semântica
(`actionId` em `ActionResult`).
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sum_service.common.contracts import generated
from sum_service.common.contracts.envelope import EnvelopeError, read_envelope
from sum_service.common.ids import new_identifier, utc_now
from sum_service.manager.domain.convergence import decide_result
from sum_service.manager.domain.errors import DuplicateWriteError, PermanentMessageError
from sum_service.manager.domain.kind import ResourceKind
from sum_service.manager.domain.outcome import Outcome, OutcomeKind
from sum_service.manager.handlers.envelope import parse_envelope
from sum_service.manager.handlers.ports import Store
from sum_service.manager.handlers.publishing import Publishing

logger = logging.getLogger(__name__)


class ResultHandler:
    """Aplica `completed` e `failed` de uma ação: conta falhas e suspende no limite."""

    def __init__(
        self,
        *,
        failure_limit: int = 5,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._failure_limit = failure_limit
        self._clock = clock
        self._publishing = Publishing(clock, identifiers)

    async def handle(
        self, store: Store, kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> Outcome:
        try:
            envelope = read_envelope(raw_message)
        except EnvelopeError as error:
            raise PermanentMessageError(error.reason) from None
        if envelope.message_type.value not in ("completed", "failed"):
            raise PermanentMessageError("a mensagem não é um resultado de ação")
        parse_envelope(
            kind, raw_message, message_type=envelope.message_type.value, emitter="executor"
        )
        if envelope.action_id is None or envelope.desired_generation is None:
            raise PermanentMessageError("resultado sem actionId ou desiredGeneration")
        try:
            async with store.transaction():
                outcome = await self._apply(store, kind, envelope)
        except DuplicateWriteError:
            outcome = Outcome(OutcomeKind.DUPLICATE)
        logger.info(
            "result handled",
            extra={
                "smarkee.resource.id": envelope.resource_id,
                "smarkee.result.type": envelope.message_type.value,
                "smarkee.outcome": outcome.kind.value,
            },
        )
        return outcome

    async def _apply(
        self, store: Store, kind: ResourceKind, envelope: generated.MessageEnvelope
    ) -> Outcome:
        assert envelope.action_id is not None and envelope.desired_generation is not None  # noqa: S101
        row = await store.lock_resource(envelope.resource_id)
        recorded = await store.record_action_result(
            action_id=envelope.action_id,
            resource_id=envelope.resource_id,
            generation=envelope.desired_generation,
            outcome=envelope.message_type.value,
        )
        if not recorded:
            return Outcome(OutcomeKind.DUPLICATE)  # resultado já contabilizado
        if row is None:
            return Outcome(OutcomeKind.IGNORED)

        generation: int = row["desired_generation"]
        if envelope.desired_generation != generation:
            return Outcome(OutcomeKind.IGNORED)  # refere-se a uma especificação substituída

        failed = envelope.message_type.value == "failed"
        decision = decide_result(
            failed=failed,
            failure_reason=str(envelope.data.get("reason", "ActionFailed")),
            failure_limit=self._failure_limit,
            generation=generation,
            failure_count=row["failure_count"],
            phase=row["phase"],
            reconciliation=row["reconciliation"],
            previous_conditions=row["conditions"],
            now=self._clock(),
        )
        resource_version = await store.save_result(
            envelope.resource_id,
            failure_count=decision.failure_count,
            phase=decision.phase,
            reconciliation=decision.reconciliation,
            conditions=decision.conditions,
        )
        await store.set_current_operations(
            envelope.resource_id,
            generation,
            status="failed" if decision.suspend else "in_progress",
            finished=decision.suspend,
        )
        if decision.suspend:
            await self._publishing.suspended_desired(
                store, kind, envelope, desired=row["desired"], generation=generation
            )
        await self._publishing.updated(
            store,
            kind,
            envelope,
            lifecycle=row["lifecycle"],
            phase=decision.phase,
            resource_version=resource_version,
            desired_generation=generation,
            observed_generation=row["observed_generation"],
        )
        return Outcome(OutcomeKind.APPLIED)
