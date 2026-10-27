"""Mapeamento das linhas do SSOT para os contratos de resposta da API (decisões 0004 e 0098).

Nunca expõe campos internos (`failure_count`, `requested_by`).
"""

from typing import Any

from ipm_role.api.domain.records import ResourceRecord
from ipm_role.common.contracts import generated

PLATFORM_ORGANIZATION_ID = "core"
"""Dado anterior à decisão 0092 não tem `organizationId`: vale `core`."""


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


OBSERVED_VIEW_FIELDS = (
    "name",
    "description",
    "permissions",
    "deletionProtection",
)
"""Campos do `observed` que a visão mostra."""


def _observed(record: ResourceRecord) -> dict[str, Any] | None:
    if record.presence is None or record.observed_at is None:
        return None
    observed = record.observed or {}
    return {
        "presence": record.presence,
        "observedAt": record.observed_at.isoformat(),
        **{field: observed[field] for field in OBSERVED_VIEW_FIELDS if field in observed},
    }


def role_view(record: ResourceRecord) -> generated.Role:
    payload = _common(record)
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "organizationId": record.desired.get("organizationId", PLATFORM_ORGANIZATION_ID),
        "name": record.desired["name"],
        "roleType": record.desired.get("roleType", "custom"),
        "description": record.desired["description"],
        "permissions": record.desired["permissions"],
        "deletionProtection": record.desired.get("deletionProtection", True) is not False,
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.Role.model_validate(payload)
