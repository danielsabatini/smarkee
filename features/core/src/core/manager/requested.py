"""Tratamento de `requested` pelo Manager.

Cada mensagem é uma unidade atômica de gravação (`docs/SSOT.md` §10.1 e
`docs/POSTGRESQL.md` §8 a §11): a linha do recurso é bloqueada antes de qualquer leitura de
estado, a Operation é gravada uma única vez e o `desired` vai para o outbox na mesma
transação. A confirmação ao transporte é responsabilidade de quem chama, **depois** do retorno
(depois do `COMMIT`).

Falhas transitórias (conexão perdida, `lock_timeout`, deadlock) propagam como exceção do
psycopg para o chamador repetir a mensagem. Reentrega e repetição do cliente retornam
`DUPLICATE`, sem gravar.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from core.contracts import generated
from core.ids import new_identifier, utc_now
from core.manager.errors import PermanentMessageError
from core.manager.kinds import MODULE, ResourceKind
from core.manager.outcome import Outcome, OutcomeKind, RejectionReason
from core.manager.policies import Request

SCHEMA_VERSION = "1.0"

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
        self._identifiers = identifiers

    async def handle(
        self,
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        raw_message: Mapping[str, Any],
    ) -> Outcome:
        envelope = self._parse_envelope(kind, raw_message)
        request = kind.policy.parse(envelope.operation.value, envelope.data)
        try:
            async with connection.transaction():
                outcome = await self._apply(connection, kind, envelope, request)
        except psycopg.errors.UniqueViolation:
            # Duas entregas simultâneas do mesmo pedido disputam a chave primária: a segunda é
            # tratada como reentrega (docs/POSTGRESQL.md §8).
            outcome = Outcome(OutcomeKind.DUPLICATE)
        logger.info(
            "requested handled",
            extra={
                "resource_type": kind.resource_type,
                "resource_id": envelope.resource_id,
                "operation_id": request.operation_id,
                "operation": request.operation,
                "outcome": outcome.kind.value,
                "reason": outcome.reason.value if outcome.reason else None,
            },
        )
        if outcome.digest_mismatch:
            logger.warning(
                "request digest differs from the recorded operation",
                extra={"resource_type": kind.resource_type, "operation_id": request.operation_id},
            )
        return outcome

    # ------------------------------------------------------------------ envelope

    @staticmethod
    def _parse_envelope(
        kind: ResourceKind, raw_message: Mapping[str, Any]
    ) -> generated.MessageEnvelope:
        try:
            envelope = generated.MessageEnvelope.model_validate(raw_message)
        except ValidationError as error:
            fields = ", ".join(
                ".".join(str(part) for part in item["loc"]) for item in error.errors()
            )
            raise PermanentMessageError(f"envelope inválido nos campos: {fields}") from None
        if (
            envelope.message_type.value != "requested"
            or envelope.emitter.value != "api"
            or envelope.module != MODULE
            or envelope.resource_type != kind.resource_type
        ):
            raise PermanentMessageError("a mensagem não é um requested da API para este tipo")
        if envelope.requested_by is None or envelope.correlation_id is None:
            raise PermanentMessageError("requested sem requestedBy ou correlationId")
        return envelope

    # ------------------------------------------------------------------ transação

    async def _apply(
        self,
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
    ) -> Outcome:
        now = self._clock()
        recorded_digest = await self._recorded_digest(connection, kind, request.operation_id)
        if recorded_digest is not None:
            return Outcome(
                OutcomeKind.DUPLICATE, digest_mismatch=recorded_digest != request.request_digest
            )
        if request.operation == "create":
            return await self._create(connection, kind, envelope, request, now)
        return await self._change(connection, kind, envelope, request, now)

    async def _create(
        self,
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
    ) -> Outcome:
        requested_by = _require(envelope.requested_by)
        desired = kind.policy.desired_for_create(request, requested_by)
        rejection = await kind.policy.check(
            connection,
            kind.table,
            request=request,
            requested_by=requested_by,
            resource_id=envelope.resource_id,
            desired=desired,
            current=None,
        )
        if rejection is not None:
            await self._insert_operation(
                connection, kind, envelope, request, now, status="rejected", reason=rejection
            )
            return Outcome(OutcomeKind.REJECTED, rejection)

        await connection.execute(
            sql.SQL(
                "INSERT INTO {table} (resource_id, schema_version, lifecycle, reconciliation,"
                " desired, desired_generation, resource_version, phase)"
                " VALUES (%s, %s, %s, 'active', %s, 1, 1, 'Pending')"
            ).format(table=kind.table),
            (envelope.resource_id, SCHEMA_VERSION, desired["lifecycle"], Jsonb(desired)),
        )
        await self._insert_operation(
            connection, kind, envelope, request, now, status="accepted", generation=1
        )
        await self._publish_desired(connection, kind, envelope, desired, "active", 1, now)
        return Outcome(OutcomeKind.ACCEPTED)

    async def _change(
        self,
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
    ) -> Outcome:
        requested_by = _require(envelope.requested_by)
        row = await self._lock_resource(connection, kind, envelope.resource_id)
        if row is None:
            return await self._reject(
                connection, kind, envelope, request, now, RejectionReason.NOT_FOUND
            )
        if row["resource_version"] != request.resource_version:
            return await self._reject(
                connection, kind, envelope, request, now, RejectionReason.CONFLICT
            )

        current: dict[str, Any] = row["desired"]
        if request.operation == "update":
            if row["lifecycle"] != "present":
                return await self._reject(
                    connection, kind, envelope, request, now, RejectionReason.VALIDATION
                )
            desired = kind.policy.desired_for_update(current, request)
        else:
            desired = kind.policy.desired_for_delete(current)

        rejection = await kind.policy.check(
            connection,
            kind.table,
            request=request,
            requested_by=requested_by,
            resource_id=envelope.resource_id,
            desired=desired,
            current=current,
        )
        if rejection is not None:
            return await self._reject(connection, kind, envelope, request, now, rejection)

        specification_changed = desired != current
        # Nova geração volta a reconciliar, salvo declaração em contrário (docs/SSOT.md §10.4).
        reconciliation = request.reconciliation or (
            "active" if specification_changed else row["reconciliation"]
        )
        if not specification_changed and reconciliation == row["reconciliation"]:
            await self._insert_operation(
                connection,
                kind,
                envelope,
                request,
                now,
                status="completed",
                generation=row["desired_generation"],
            )
            return Outcome(OutcomeKind.COMPLETED)

        phase = row["phase"]
        if specification_changed:
            phase = "Deleting" if desired["lifecycle"] == "absent" else "Reconciling"
        cursor = connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "UPDATE {table} SET lifecycle = %s, reconciliation = %s, desired = %s,"
                " desired_generation = desired_generation"
                "   + (CASE WHEN desired IS DISTINCT FROM %s THEN 1 ELSE 0 END),"
                " failure_count ="
                "   CASE WHEN desired IS DISTINCT FROM %s THEN 0 ELSE failure_count END,"
                " phase = %s, resource_version = resource_version + 1, updated_at = now()"
                " WHERE resource_id = %s AND resource_version = %s"
                " RETURNING desired_generation"
            ).format(table=kind.table),
            (
                desired["lifecycle"],
                reconciliation,
                Jsonb(desired),
                Jsonb(desired),
                Jsonb(desired),
                phase,
                envelope.resource_id,
                request.resource_version,
            ),
        )
        updated = await cursor.fetchone()
        if updated is None:
            # Defensivo: a linha está bloqueada e a versão foi conferida; zero linhas = conflito.
            return await self._reject(
                connection, kind, envelope, request, now, RejectionReason.CONFLICT
            )
        generation: int = updated["desired_generation"]
        await self._insert_operation(
            connection,
            kind,
            envelope,
            request,
            now,
            status="accepted" if specification_changed else "completed",
            generation=generation,
        )
        await self._publish_desired(
            connection, kind, envelope, desired, reconciliation, generation, now
        )
        return Outcome(OutcomeKind.ACCEPTED if specification_changed else OutcomeKind.COMPLETED)

    # ------------------------------------------------------------------ SQL

    @staticmethod
    async def _recorded_digest(
        connection: AsyncConnection[Any], kind: ResourceKind, operation_id: str
    ) -> str | None:
        cursor = await connection.execute(
            sql.SQL("SELECT request_digest FROM {table} WHERE operation_id = %s").format(
                table=kind.operation_table
            ),
            (operation_id,),
        )
        row = await cursor.fetchone()
        return None if row is None else str(row[0])

    @staticmethod
    async def _lock_resource(
        connection: AsyncConnection[Any], kind: ResourceKind, resource_id: str
    ) -> dict[str, Any] | None:
        cursor = connection.cursor(row_factory=dict_row)
        await cursor.execute(
            sql.SQL(
                "SELECT resource_version, desired_generation, lifecycle, reconciliation,"
                " desired, phase FROM {table} WHERE resource_id = %s FOR UPDATE"
            ).format(table=kind.table),
            (resource_id,),
        )
        return await cursor.fetchone()

    async def _reject(
        self,
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
        reason: RejectionReason,
    ) -> Outcome:
        await self._insert_operation(
            connection, kind, envelope, request, now, status="rejected", reason=reason
        )
        return Outcome(OutcomeKind.REJECTED, reason)

    @staticmethod
    async def _insert_operation(
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        request: Request,
        now: datetime,
        *,
        status: str,
        generation: int | None = None,
        reason: RejectionReason | None = None,
    ) -> None:
        await connection.execute(
            sql.SQL(
                "INSERT INTO {table} (operation_id, resource_id, operation_type,"
                " desired_generation, requested_by, correlation_id, request_digest,"
                " operation_status, operation_status_reason, completed_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(table=kind.operation_table),
            (
                request.operation_id,
                envelope.resource_id,
                request.operation,
                generation,
                _require(envelope.requested_by),
                _require(envelope.correlation_id),
                request.request_digest,
                status,
                reason.value if reason else None,
                now if status == "completed" else None,
            ),
        )

    async def _publish_desired(
        self,
        connection: AsyncConnection[Any],
        kind: ResourceKind,
        envelope: generated.MessageEnvelope,
        desired: Mapping[str, Any],
        reconciliation: str,
        generation: int,
        now: datetime,
    ) -> None:
        message = generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "desired",
                "emitter": "manager",
                "module": MODULE,
                "resourceType": kind.resource_type,
                "resourceId": envelope.resource_id,
                "operation": "changed",
                "desiredGeneration": generation,
                "requestedBy": _require(envelope.requested_by),
                "correlationId": _require(envelope.correlation_id),
                "causationId": envelope.message_id,
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": kind.policy.message_data(desired, reconciliation),
            }
        ).model_dump(mode="json", exclude_none=True)
        subject = f"manager.desired.{MODULE}.{kind.resource_type}.{envelope.resource_id}.changed"
        await connection.execute(
            sql.SQL(
                "INSERT INTO {table} (message_id, resource_id, subject, payload)"
                " VALUES (%s, %s, %s, %s)"
            ).format(table=kind.outbox_table),
            (message["messageId"], envelope.resource_id, subject, Jsonb(message)),
        )


def _require[T](value: T | None) -> T:
    if value is None:
        raise PermanentMessageError("campo obrigatório ausente")
    return value
