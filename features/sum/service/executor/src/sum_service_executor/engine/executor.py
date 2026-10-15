"""Motor do Executor de `sum.service`: executa uma `action` no Zitadel e publica o resultado.

Cada `action` é revalidada contra o `desired` atual (`docs/RESOURCE-CONTROL-LOOP.md`): se a geração
mudou, a ação é velha e não é executada. Concede as roles pedidas (ligar) ou revoga as roles do
serviço
(desligar). Repetir é seguro (o provider é idempotente), então erro transitório não vira `failed`: a
mensagem volta à fila. Erro permanente vira `failed`, com o motivo.
"""

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from pydantic import ValidationError

from sum_service_executor.actions.service_roles import Granter, disable, enable
from sum_service_executor.contracts import generated
from sum_service_executor.contracts.base import supports_major, validate_tolerant
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


class DesiredReader(Protocol):
    async def current(self, resource_id: str) -> bytes | None:
        """O último `desired` publicado para o recurso (leitura direta do Stream `DESIRED`)."""
        ...


class TransientFailureError(Exception):
    """Falha que repetir pode resolver: a mensagem volta à fila e a ação é tentada de novo."""


class Executor:
    def __init__(
        self,
        granter: Granter,
        desired: DesiredReader,
        publisher: Publisher,
        catalog: Mapping[str, tuple[str, ...]],
        *,
        clock: Callable[[], Any] = utc_now,
        identifiers: Callable[[], str] = new_identifier,
    ) -> None:
        self._granter = granter
        self._desired = desired
        self._publisher = publisher
        self._catalog = catalog
        self._clock = clock
        self._identifiers = identifiers

    async def on_action(self, data: bytes) -> None:
        """Executa uma `action`. Levanta `TransientFailureError` para voltar à fila; publica o
        resultado."""
        envelope = _parse(data, "action")
        if envelope is None:
            return
        action = _Action(envelope)
        desired = await self._current_desired(action.resource_id)
        if desired is None or desired["generation"] != action.desired_generation:
            return  # ação velha: a geração mudou; o Reconciler decide de novo
        try:
            await self._apply(action.resource_id, desired)
        except ProviderError as error:
            if error.retryable:
                raise TransientFailureError(error.reason) from None
            await self._publish_result(
                "failed", action, reason=error.reason, message=str(error), retryable=False
            )
            return
        await self._publish_result("completed", action)

    async def _current_desired(self, resource_id: str) -> dict[str, Any] | None:
        raw = await self._desired.current(resource_id)
        if raw is None:
            return None
        envelope = _parse(raw, "desired")
        if envelope is None:
            return None
        data: Mapping[str, Any] = envelope.data
        return {
            "generation": envelope.desired_generation,
            "lifecycle": str(data.get("lifecycle", "present")),
            "owner": str(data.get("ownerUserId", "")),
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
        logger.info("service roles revoked", extra={"resource_id": resource_id})

    async def _publish_result(
        self,
        kind: str,
        action: _Action,
        *,
        reason: str | None = None,
        message: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        now = self._clock().strftime("%Y-%m-%dT%H:%M:%SZ")
        data: dict[str, Any] = {}
        if kind == "failed":
            data = {
                "reason": reason or "Rejected",
                "message": (message or "")[:512],
                "retryable": bool(retryable),
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


def _parse(data: bytes, expected: str) -> generated.MessageEnvelope | None:
    try:
        envelope = validate_tolerant(generated.MessageEnvelope, json.loads(data))
    except ValueError, ValidationError:
        logger.error("message is not a valid envelope")
        return None
    if not supports_major(envelope.schema_version) or envelope.module != MODULE:
        return None
    if envelope.message_type.value != expected or envelope.resource_type != RESOURCE_TYPE:
        return None
    return envelope
