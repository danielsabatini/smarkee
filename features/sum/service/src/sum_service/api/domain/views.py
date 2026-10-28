"""Mapeamento das linhas do SSOT para os contratos de resposta da API.

Nunca expõe campos internos (`failure_count`, `requested_by`, `correlation_id`).
"""

from typing import Any

from sum_service.api.domain.records import ResourceRecord
from sum_service.common.contracts import generated


def service_view(record: ResourceRecord) -> generated.ServiceResource:
    payload: dict[str, Any] = {
        "resourceId": record.resource_id,
        "resourceVersion": str(record.resource_version),
        "desiredGeneration": record.desired_generation,
        **(
            {"observedGeneration": record.observed_generation}
            if record.observed_generation is not None
            else {}
        ),
        "phase": record.phase,
        "conditions": record.conditions,
        "desired": record.desired,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }
    # O contrato `ServiceObservedData` só tem as permissões; ausente antes da primeira observação.
    if record.presence is not None and record.observed is not None:
        payload["observed"] = record.observed
    return generated.ServiceResource.model_validate(payload)
