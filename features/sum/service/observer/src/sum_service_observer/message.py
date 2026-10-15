"""Mensagem `observed` de `sum.service` (`docs/RESOURCE-CONTROL-LOOP.md`; decisão 0033).

O Observer publica o estado lido do Zitadel. Não decide: quem compara é o Reconciler.
"""

from datetime import datetime
from typing import Any

from sum_service_observer.contracts import generated
from sum_service_observer.domain.observation import Observation

MODULE = "sum"
RESOURCE_TYPE = "service"
SCHEMA_VERSION = "1.0"
PUBLISHED_BY = "sum-service-observer"


def subject_of(resource_id: str) -> str:
    return f"observer.observed.{MODULE}.{RESOURCE_TYPE}.{resource_id}.changed"


def observed_envelope(
    *,
    message_id: str,
    resource_id: str,
    observation: Observation,
    correlation_id: str,
    causation_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    """Envelope validado do `observed`. Sai só se atende ao contrato."""
    document: dict[str, Any] = {
        "messageId": message_id,
        "schemaVersion": SCHEMA_VERSION,
        "messageType": "observed",
        "emitter": "observer",
        "module": MODULE,
        "resourceType": RESOURCE_TYPE,
        "resourceId": resource_id,
        "operation": "changed",
        "presence": observation.presence,
        "observedAt": now,
        "correlationId": correlation_id,
        "occurredAt": now,
        "publishedAt": now,
        "publishedBy": PUBLISHED_BY,
        "data": observation.data,
    }
    if causation_id is not None:
        document["causationId"] = causation_id
    envelope = generated.MessageEnvelope.model_validate(document)
    return envelope.model_dump(by_alias=True, mode="json", exclude_none=True)
