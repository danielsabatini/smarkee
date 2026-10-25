"""Tratamento de `requested` pelo Manager.

Cada mensagem é uma unidade atômica de gravação (`docs/SSOT.md` §10.1 e
`docs/POSTGRESQL.md` §8 a §11): a linha do recurso é bloqueada antes de qualquer leitura de
estado, a Operation é gravada uma única vez e o `desired` vai para o outbox na mesma
transação. A confirmação ao transporte é responsabilidade de quem chama, **depois** do retorno
(depois do `COMMIT`).

Falhas transitórias do banco propagam como exceção para o chamador repetir a mensagem. Reentrega e
repetição do cliente retornam `DUPLICATE`, sem gravar.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from ipm_role.common.contracts import generated
from ipm_role.common.ids import new_identifier, utc_now
from ipm_role.common.resource import SCHEMA_VERSION
from ipm_role.manager.domain.errors import DuplicateWriteError, PermanentMessageError
from ipm_role.manager.domain.kind import ResourceKind
from ipm_role.manager.domain.outcome import Outcome, OutcomeKind, RejectionReason
from ipm_role.manager.domain.policy import Request
from ipm_role.manager.handlers.envelope import parse_envelope, require
from ipm_role.manager.handlers.ports import Store
from ipm_role.manager.handlers.publishing import Publishing

logger = logging.getLogger(__name__)


class RequestedHandler:
    """Aplica um `requested` ao SSOT de um tipo de recurso."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._clock = clock
        self._publishing = Publishing(clock, identifiers)

    async def handle(
        self, store: Store, kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> Outcome:
        envelope = parse_envelope(kind, raw_message, message_type="requested", emitter="receiver")
        if envelope.requested_by is None or envelope.correlation_id is None:
            raise PermanentMessageError("requested sem requestedBy ou correlationId")
        request = kind.policy.parse(envelope.operation.value, envelope.data)
        try:
            async with store.transaction():
                outcome = await self._apply(store, kind, envelope, request)
        except DuplicateWriteError:
            outcome = Outcome(OutcomeKind.DUPLICATE)
        logger.info(
            "requested handled",
            extra={
                "smarkee.resource.id": envelope.resource_id,
                "smarkee.operation.id": request.operation_id,
                "smarkee.operation.name": request.operation,
                "smarkee.outcome": outcome.kind.value,
                "smarkee.reason": outcome.reason.value if outcome.reason else None,
            },
        )
        if outcome.digest_mismatch:
            logger.warning(
                "request digest differs from the recorded operation",
                extra={"smarkee.operation.id": request.operation_id},
            )
        return outcome

    async def _apply(
        self,
        store: Store,
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
    ) -> Outcome:
        now = self._clock()
        recorded_digest = await store.recorded_digest(request.operation_id)
        if recorded_digest is not None:
            return Outcome(
                OutcomeKind.DUPLICATE, digest_mismatch=recorded_digest != request.request_digest
            )
        if request.operation == "create":
            return await self._create(store, kind, envelope, request, now)
        return await self._change(store, kind, envelope, request, now)

    async def _create(
        self,
        store: Store,
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
    ) -> Outcome:
        desired = kind.policy.desired_for_create(request, require(envelope.requested_by))
        rejection = await self._rejection(store, kind, envelope.resource_id, desired)
        if rejection is not None:
            await self._record_operation(
                store, envelope, request, now, status="rejected", reason=rejection
            )
            return Outcome(OutcomeKind.REJECTED, rejection)

        await store.insert_resource(
            envelope.resource_id, schema_version=SCHEMA_VERSION, desired=desired
        )
        await self._record_operation(store, envelope, request, now, status="accepted", generation=1)
        await self._publishing.desired(
            store, kind, envelope, desired=desired, reconciliation="active", generation=1
        )
        return Outcome(OutcomeKind.ACCEPTED)

    async def _change(
        self,
        store: Store,
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
    ) -> Outcome:
        row = await store.lock_for_request(envelope.resource_id)
        if row is None:
            return await self._reject(store, envelope, request, now, RejectionReason.NOT_FOUND)
        if row["resource_version"] != request.resource_version:
            return await self._reject(store, envelope, request, now, RejectionReason.CONFLICT)

        current: dict[str, Any] = row["desired"]
        if request.operation == "delete" and kind.policy.deletion_protected(current):
            return await self._reject(store, envelope, request, now, RejectionReason.PROTECTED)
        if request.operation == "update":
            if row["lifecycle"] != "present":
                return await self._reject(store, envelope, request, now, RejectionReason.VALIDATION)
            desired = kind.policy.desired_for_update(current, request)
        else:
            desired = kind.policy.desired_for_delete(current)

        rejection = await self._rejection(store, kind, envelope.resource_id, desired)
        if rejection is not None:
            return await self._reject(store, envelope, request, now, rejection)

        specification_changed = desired != current
        # Nova geração volta a reconciliar, salvo declaração em contrário (docs/SSOT.md §10.4).
        reconciliation = request.reconciliation or (
            "active" if specification_changed else row["reconciliation"]
        )
        # Sem geração nova (nada mudou, ou só a `reconciliation` do operador), a Operation acompanha
        # a geração vigente: conclui já se ela estiver confirmada pela observação, senão quando for.
        confirmed = row["observed_generation"] == row["desired_generation"]
        if not specification_changed and reconciliation == row["reconciliation"]:
            await self._record_operation(
                store,
                envelope,
                request,
                now,
                status="completed" if confirmed else "accepted",
                generation=row["desired_generation"],
            )
            return Outcome(OutcomeKind.COMPLETED if confirmed else OutcomeKind.ACCEPTED)

        # Toda alteração do `desired` percorre o loop, inclusive a de campo da plataforma (como a
        # proteção contra exclusão): o Reconciler decide (action ou noop) e a Operation conclui na
        # observação da nova geração, como no Kubernetes (decisão 0072).
        phase = row["phase"]
        if specification_changed:
            phase = "Deleting" if desired["lifecycle"] == "absent" else "Reconciling"
        generation = await store.change_desired(
            envelope.resource_id,
            desired=desired,
            reconciliation=reconciliation,
            phase=phase,
            expected_resource_version=request.resource_version,
        )
        if generation is None:
            # Defensivo: a linha está bloqueada e a versão foi conferida; zero linhas = conflito.
            return await self._reject(store, envelope, request, now, RejectionReason.CONFLICT)
        done = not specification_changed and confirmed
        await self._record_operation(
            store,
            envelope,
            request,
            now,
            status="completed" if done else "accepted",
            generation=generation,
        )
        await self._publishing.desired(
            store,
            kind,
            envelope,
            desired=desired,
            reconciliation=reconciliation,
            generation=generation,
        )
        return Outcome(OutcomeKind.COMPLETED if done else OutcomeKind.ACCEPTED)

    @staticmethod
    async def _rejection(
        store: Store,
        kind: ResourceKind,
        resource_id: str,
        desired: Mapping[str, Any],
    ) -> RejectionReason | None:
        """Regras do tipo sobre o `desired`: valor recusado e valor único.

        Cada uma é conferida na mesma transação do pedido, com trava consultiva por chave.
        """
        if kind.policy.invalid(desired):
            return RejectionReason.VALIDATION
        unique = kind.policy.unique_value(desired)
        if unique is not None and await store.value_in_use(
            unique, excluding_resource_id=resource_id
        ):
            return RejectionReason.VALIDATION
        return None

    async def _reject(
        self,
        store: Store,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
        reason: RejectionReason,
    ) -> Outcome:
        await self._record_operation(
            store, envelope, request, now, status="rejected", reason=reason
        )
        return Outcome(OutcomeKind.REJECTED, reason)

    @staticmethod
    async def _record_operation(
        store: Store,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
        *,
        status: str,
        generation: int | None = None,
        reason: RejectionReason | None = None,
    ) -> None:
        await store.insert_operation(
            operation_id=request.operation_id,
            resource_id=envelope.resource_id,
            operation_type=request.operation,
            generation=generation,
            requested_by=require(envelope.requested_by),
            correlation_id=require(envelope.correlation_id),
            request_digest=request.request_digest,
            status=status,
            reason=reason.value if reason else None,
            completed_at=now if status == "completed" else None,
        )
