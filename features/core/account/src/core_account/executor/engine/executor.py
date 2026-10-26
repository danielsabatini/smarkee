"""Motor do Executor: revalida a `action`, executa no Zitadel e publica `completed` ou `failed`.

O Executor é o último ponto de controle antes do sistema externo
(`docs/loop/RESOURCE-CONTROL-SECURITY.md` §7): ele **não** confia cegamente em quem lhe enviou a
`action`. Antes de escrever, confere o `desired` vigente (geração, coerência da operação,
reconciliação ativa) e o desfecho já registrado do `actionId`. Falhas do provedor viram `failed`
(com `retryable`), e o retry é do Reconciler, sob backoff.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from core_account.common.contracts import generated
from core_account.common.contracts.envelope import EnvelopeError, read_envelope
from core_account.common.ids import new_identifier, utc_now
from core_account.common.ports import Publisher
from core_account.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION
from core_account.executor.actions.account_actions import Drivers, execute
from core_account.executor.domain.errors import ActionFailedError
from core_account.executor.domain.identity import ProviderError
from core_account.executor.domain.revalidation import revalidate

logger = logging.getLogger(__name__)


class StateReader(Protocol):
    """Leitura direta e somente leitura do último valor de um Subject (Direct Get)."""

    async def last_desired(self, resource_id: str) -> Mapping[str, Any] | None: ...

    async def last_result(
        self, resource_id: str, operation: str, kind: str
    ) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class Outcome:
    """Desfecho de uma ação: sucesso (`failure is None`) ou a falha."""

    failure: ActionFailedError | None


class Disposition(StrEnum):
    ACK = "ack"
    TERM = "term"


class Executor:
    def __init__(
        self,
        drivers: Drivers,
        publisher: Publisher,
        state: StateReader,
        *,
        clock: Callable[[], datetime] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._drivers = drivers
        self._publisher = publisher
        self._state = state
        self._clock = clock
        self._identifiers = identifiers

    async def handle(self, data: bytes) -> Disposition:
        action = self._parse(data)
        if action is None:
            return Disposition.TERM  # nunca será válida: não reprocessa
        resource_id = action.resource_id
        operation = action.operation.value

        # 1. Desfecho já registrado do mesmo actionId: não executa de novo (idempotência).
        previous = await self._previous_outcome(action)
        if previous is not None:
            await self._publish_result(action, previous.failure)
            return Disposition.ACK

        # 2. Revalidação contra o desired vigente.
        desired = await self._state.last_desired(resource_id)
        failure = revalidate(operation, action.desired_generation, desired)
        if failure is None and desired is not None:
            data_: Mapping[str, Any] = desired.get("data") or {}
            try:
                await execute(operation, resource_id, data_, self._drivers)
            except ActionFailedError as error:
                failure = error
            except ProviderError as error:
                failure = ActionFailedError(
                    error.reason, retryable=error.retryable, message=str(error)
                )
        await self._publish_result(action, failure)
        logger.info(
            "action handled",
            extra={
                "smarkee.resource.id": resource_id,
                "smarkee.operation.name": operation,
                "smarkee.outcome": "completed" if failure is None else "failed",
                "smarkee.reason": failure.reason if failure else None,
            },
        )
        return Disposition.ACK

    # ------------------------------------------------------------------ validação

    @staticmethod
    def _parse(data: bytes) -> generated.MessageEnvelope | None:
        try:
            envelope = read_envelope(data)
        except EnvelopeError as error:
            logger.error("action rejected", extra={"smarkee.reason": error.reason})
            return None
        if (
            envelope.message_type.value != "action"
            or envelope.emitter.value != "reconciler"
            or envelope.module != MODULE
            or envelope.resource_type != RESOURCE_TYPE
            or envelope.action_id is None
            or envelope.desired_generation is None
        ):
            logger.error("message is not an action of the reconciler for this type")
            return None
        return envelope

    async def _previous_outcome(self, action: generated.MessageEnvelope) -> Outcome | None:
        """Desfecho já registrado para o `actionId`, lido do transporte (somente leitura).

        `completed` do mesmo `actionId` e `failed` **permanente** do mesmo `actionId` não são
        executados de novo. Um `failed` retentável não bloqueia: a repetição é o objetivo.
        """
        operation = action.operation.value
        completed = await self._state.last_result(action.resource_id, operation, "completed")
        if completed is not None and completed.get("actionId") == action.action_id:
            return Outcome(None)
        failed = await self._state.last_result(action.resource_id, operation, "failed")
        if failed is not None and failed.get("actionId") == action.action_id:
            data: Mapping[str, Any] = failed.get("data") or {}
            if data.get("retryable") is False:
                return Outcome(
                    ActionFailedError(
                        str(data.get("reason", "Rejected")),
                        retryable=False,
                        message=str(data.get("message", "")),
                    )
                )
        return None

    async def _publish_result(
        self, action: generated.MessageEnvelope, failure: ActionFailedError | None
    ) -> None:
        now = self._clock()
        failed = failure is not None
        data: dict[str, Any] = {}
        if failure is not None:
            data = {"reason": failure.reason, "retryable": failure.retryable}
            if failure.message:
                data["message"] = failure.message
        envelope = generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "failed" if failed else "completed",
                "emitter": "executor",
                "module": MODULE,
                "resourceType": RESOURCE_TYPE,
                "resourceId": action.resource_id,
                "operation": action.operation.value,
                "actionId": action.action_id,
                "desiredGeneration": action.desired_generation,
                **({"requestedBy": action.requested_by} if action.requested_by else {}),
                "correlationId": action.correlation_id or self._identifiers(),
                "causationId": action.message_id,
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": data,
            }
        )
        kind = "failed" if failed else "completed"
        operation = action.operation.value
        subject = f"executor.{kind}.{MODULE}.{RESOURCE_TYPE}.{action.resource_id}.{operation}"
        await self._publisher.publish(
            subject,
            envelope.model_dump_json(exclude_none=True).encode(),
            message_id=envelope.message_id,
        )
