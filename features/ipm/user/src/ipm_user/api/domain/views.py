"""Mapeamento das linhas do SSOT para os contratos de resposta da API.

Nunca expõe campos internos (`failure_count`, `requested_by`, `correlation_id`).
"""

from typing import Any

from ipm_user.api.domain.records import ResourceRecord
from ipm_user.common.contracts import generated

PERSONAL_FIELDS = ("givenName", "familyName", "email")
"""Dados pessoais do `desired`; saem dele na remoção (`schemas/ipm/user/desired`)."""


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


def user_view(record: ResourceRecord) -> generated.User:
    payload = _common(record)
    desired = record.desired
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "organizationId": desired["organizationId"],
        **({"roles": desired["roles"]} if "roles" in desired else {}),
        **({"groups": desired["groups"]} if "groups" in desired else {}),
        # No usuário da Organization a proteção nasce desligada (decisão 0077).
        "deletionProtection": desired.get("deletionProtection", False),
        **{field: desired[field] for field in PERSONAL_FIELDS if field in desired},
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.User.model_validate(payload)
