"""Comando de admissão: o que uma escrita da API pede ao SSOT, validado e sem I/O (decisão 0098)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sum_service.common.contracts import generated
from sum_service.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION

Operation = Literal["create", "delete"]


@dataclass(frozen=True, slots=True)
class Admission:
    """Uma escrita a admitir numa única transação do SSOT."""

    operation: Operation
    resource_id: str
    requested_by: str
    correlation_id: str
    request_digest: str
    now: datetime
    message_id: str
    idempotency_key: str | None = None
    resource_version: int | None = None
    """Versão lida pelo cliente (`delete`); divergência é `409`."""

    service: str | None = None
    """Create: o serviço a ligar. O dono é o solicitante (`requested_by`), nunca o corpo."""


def desired_message(
    admission: Admission,
    *,
    generation: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Envelope do `desired` que vai para o outbox (emissor `api`, decisão 0098)."""
    return generated.MessageEnvelope.model_validate(
        {
            "messageId": admission.message_id,
            "schemaVersion": SCHEMA_VERSION,
            "messageType": "desired",
            "emitter": "api",
            "module": MODULE,
            "resourceType": RESOURCE_TYPE,
            "resourceId": admission.resource_id,
            "operation": "changed",
            "desiredGeneration": generation,
            "requestedBy": admission.requested_by,
            "correlationId": admission.correlation_id,
            "occurredAt": admission.now.isoformat(),
            "publishedAt": admission.now.isoformat(),
            "data": data,
        }
    ).model_dump(mode="json", exclude_none=True)


def desired_subject(resource_id: str) -> str:
    return f"desired.{MODULE}.{RESOURCE_TYPE}.{resource_id}"
