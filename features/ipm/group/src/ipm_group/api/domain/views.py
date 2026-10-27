"""Mapeamento das linhas do SSOT para os contratos de resposta da API (decisões 0088 e 0098).

Nunca expõe campos internos (`failure_count`, `requested_by`).
"""

from typing import Any

from ipm_group.api.domain.records import ResourceRecord
from ipm_group.common.contracts import generated


def _common(record: ResourceRecord) -> dict[str, Any]:
    return {
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
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _observed(record: ResourceRecord) -> dict[str, Any] | None:
    if record.presence is None or record.observed_at is None:
        return None
    return {
        "presence": record.presence,
        "observedAt": record.observed_at.isoformat(),
        **(record.observed or {}),
    }


def group_view(record: ResourceRecord) -> generated.Group:
    payload = _common(record)
    desired = record.desired
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "organizationId": desired["organizationId"],
        "name": desired["name"],
        "description": desired["description"],
        "roles": desired.get("roles", []),
        "deletionProtection": desired.get("deletionProtection", False),
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.Group.model_validate(payload)
