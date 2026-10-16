"""Motor do Executor de `sum.service`: executa uma `action` no Zitadel e publica o resultado.

Cada `action` é validada (emissor, tipo, módulo) e revalidada contra o `desired` atual
(`docs/RESOURCE-CONTROL-SECURITY.md` §7): geração, suspensão e `lifecycle`. Uma ação recusada ou
velha vira `failed` (permanente), nunca é executada. Concede as roles pedidas (ligar) ou revoga as
roles do serviço (desligar). Um `actionId` com desfecho já registrado não é executado de novo.
Erro transitório não vira `failed`: a mensagem volta à fila.
"""

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import ValidationError

from sum_service_executor.actions.service_roles import Granter, disable, enable
from sum_service_executor.contracts import generated
from sum_service_executor.contracts.base import supports_major, validate_tolerant
from sum_service_executor.domain.errors import ActionFailedError
from sum_service_executor.domain.revalidation import revalidate
from sum_service_executor.domain.service import roles_of
from sum_service_executor.ids import new_identifier, utc_now
from sum_service_executor.provider.zitadel import ProviderError

MODULE = "sum"
RESOURCE_TYPE = "service"
SCHEMA_VERSION = "1.0"
PUBLISHED_BY = "sum-service-executor"

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """O transporte não confirmou a publicação do resultado; a ação volta à fila."""


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None: ...


class StateReader(Protocol):
    """Leitura direta do transporte, só leitura (último `desired` e último resultado)."""

    async def last_desired(self, resource_id: str) -> bytes | None:
        """O último `desired` publicado para o recurso (Stream `DESIRED`)."""
        ...

    async def last_result(self, resource_id: str, kind: str) -> bytes | None:
        """O último resultado `completed` ou `failed` do recurso (Stream `RESULT`)."""
        ...


@dataclass(frozen=True, slots=True)
class _Outcome:
    """Desfecho já registrado de um `actionId`. `failure` vazio é `completed`."""

    failure: ActionFailedError | None


class TransientFailureError(Exception):
    """Falha que repetir pode resolver: a mensagem volta à fila e a ação é tentada de novo."""


class Executor:
    def __init__(
        self,
        granter: Granter,
        state: StateReader,
        publisher: Publisher,
        catalog: Mapping[str, tuple[str, ...]],
        *,
        clock: Callable[[], Any] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._granter = granter
        self._state = state
        self._publisher = publisher
        self._catalog = catalog
        self._clock = clock
        self._identifiers = identifiers

    async def on_action(self, data: bytes) -> None:
        """Executa uma `action` e publica o resultado.

        Levanta `TransientFailureError` para a mensagem voltar à fila. Mensagem inválida é
        descartada.
        """
        envelope = _parse(data, expected_type="action", expected_emitter="reconciler")
        if envelope is None or envelope.action_id is None or envelope.desired_generation is None:
            logger.error("message is not a valid action of the reconciler for this type")
            return
        action = _Action(envelope)
        # 1. Desfecho já registrado do mesmo actionId: não executa de novo (idempotência).
        previous = await self._previous_outcome(action)
        if previous is not None:
            await self._publish_result(action, previous.failure)
            return
        # 2. Revalidação contra o desired vigente.
        desired = await self._current_desired(action.resource_id)
        failure = revalidate(envelope.operation.value, action.desired_generation, desired)
        if failure is None and desired is not None:
            try:
                await self._apply(action.resource_id, desired)
            except ProviderError as error:
                if error.retryable:
                    raise TransientFailureError(error.reason) from None
                failure = ActionFailedError(error.reason, retryable=False, message=str(error))
        await self._publish_result(action, failure)
        logger.info(
            "action handled",
            extra={
                "smarkee.resource.id": action.resource_id,
                "smarkee.outcome": "completed" if failure is None else "failed",
                "smarkee.reason": failure.reason if failure else None,
            },
        )

    async def _previous_outcome(self, action: _Action) -> _Outcome | None:
        """Desfecho já registrado para o `actionId`, lido do transporte (somente leitura).

        `completed` e `failed` **permanente** do mesmo `actionId` não são executados de novo.
        """
        completed = await self._last_result(action.resource_id, "completed")
        if completed is not None and completed.get("actionId") == action.action_id:
            return _Outcome(None)
        failed = await self._last_result(action.resource_id, "failed")
        if failed is not None and failed.get("actionId") == action.action_id:
            data: Mapping[str, Any] = failed.get("data") or {}
            if data.get("retryable") is False:
                return _Outcome(
                    ActionFailedError(
                        str(data.get("reason", "Rejected")),
                        retryable=False,
                        message=str(data.get("message", "")),
                    )
                )
        return None

    async def _last_result(self, resource_id: str, kind: str) -> dict[str, Any] | None:
        raw = await self._state.last_result(resource_id, kind)
        if raw is None:
            return None
        try:
            document: object = json.loads(raw)
        except ValueError:
            return None
        return cast(dict[str, Any], document) if isinstance(document, dict) else None

    async def _current_desired(self, resource_id: str) -> dict[str, Any] | None:
        raw = await self._state.last_desired(resource_id)
        if raw is None:
            return None
        envelope = _parse(raw, expected_type="desired", expected_emitter="manager")
        if envelope is None:
            return None
        data: Mapping[str, Any] = envelope.data
        return {
            "generation": envelope.desired_generation,
            "reconciliation": data.get("reconciliation"),
            # Sem `lifecycle` não há padrão: a revalidação recusa (não se assume `present`).
            "lifecycle": data.get("lifecycle"),
            "owner": str(data.get("ownerAccountId", "")),
            "service": str(data.get("service", "")),
            "roles": tuple(str(role) for role in data.get("serviceRoles", ())),
        }

    async def _apply(self, resource_id: str, desired: dict[str, Any]) -> None:
        owner, service = desired["owner"], desired["service"]
        if desired["lifecycle"] == "present":
            await enable(self._granter, owner, desired["roles"])
            return
        # Desligada: as roles são as do catálogo do serviço (a lista de `desired` vem vazia).
        await disable(self._granter, owner, roles_of(self._catalog, service))
        logger.info("service roles revoked", extra={"smarkee.resource.id": resource_id})

    async def _publish_result(self, action: _Action, failure: ActionFailedError | None) -> None:
        kind = "completed" if failure is None else "failed"
        now = self._clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        data: dict[str, Any] = {}
        if failure is not None:
            data = {
                "reason": failure.reason,
                "message": failure.message[:512],
                "retryable": failure.retryable,
            }
        message_id = self._identifiers()
        document: dict[str, Any] = {
            "messageId": message_id,
            "schemaVersion": SCHEMA_VERSION,
            "messageType": kind,
            "emitter": "executor",
            "module": MODULE,
            "resourceType": RESOURCE_TYPE,
            "resourceId": action.resource_id,
            "operation": "update",
            "actionId": action.action_id,
            "desiredGeneration": action.desired_generation,
            "correlationId": action.correlation_id,
            "causationId": action.message_id,
            "occurredAt": now,
            "publishedAt": now,
            "publishedBy": PUBLISHED_BY,
            "data": data,
        }
        generated.MessageEnvelope.model_validate(document)
        try:
            await self._publisher.publish(
                f"executor.{kind}.{MODULE}.{RESOURCE_TYPE}.{action.resource_id}",
                json.dumps(document).encode(),
                message_id=f"{action.action_id}.{kind}",
            )
        except PublishError:
            raise TransientFailureError("result publication") from None


class _Action:
    """A `action` consumida, já validada, com o que o motor precisa para publicar o resultado."""

    def __init__(self, envelope: generated.MessageEnvelope) -> None:
        self.message_id = envelope.message_id
        self.resource_id = envelope.resource_id
        self.action_id = envelope.action_id or ""
        self.desired_generation = envelope.desired_generation or 0
        self.correlation_id = envelope.correlation_id or self.message_id


def _parse(
    data: bytes, *, expected_type: str, expected_emitter: str
) -> generated.MessageEnvelope | None:
    """Envelope válido, do emissor esperado, de uma versão MAJOR suportada e deste tipo."""
    try:
        envelope = validate_tolerant(generated.MessageEnvelope, json.loads(data))
    except ValueError, ValidationError:
        logger.error("message is not a valid envelope")
        return None
    if not supports_major(envelope.schema_version):
        logger.error("schemaVersion MAJOR is not supported")
        return None
    if (
        envelope.message_type.value != expected_type
        or envelope.emitter.value != expected_emitter
        or envelope.module != MODULE
        or envelope.resource_type != RESOURCE_TYPE
    ):
        return None
    return envelope
