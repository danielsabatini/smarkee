"""Comando de admissão: o que uma escrita da API pede ao SSOT, validado e sem I/O (decisão 0098)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ipm_serviceaccount.common.contracts import generated
from ipm_serviceaccount.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION

Operation = Literal["create", "update", "delete"]


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
    """Versão lida pelo cliente (`update` e `delete`); divergência é `409`."""

    specification: Mapping[str, Any] | None = None
    """Create: a especificação inteira. Update: só os campos alterados."""

    reconciliation: str | None = None
    quota_limit: int | None = None
    """Service accounts por Organization para quem não é operador (só no create)."""


def desired_message(
    admission: Admission,
    *,
    desired: Mapping[str, Any],
    reconciliation: str,
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
    # O subject mantém o emissor `manager` (dono do SSOT do tipo): ACL e Streams não mudam.
    return f"manager.desired.{MODULE}.{RESOURCE_TYPE}.{resource_id}.changed"
