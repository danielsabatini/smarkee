"""Mapeamento das linhas do SSOT para os contratos de resposta da API.

Nunca expõe campos internos (`failure_count`, `requested_by`, `correlation_id`).
"""

from typing import Any

from core_account.api.domain.account import PERSONAL_FIELDS
from core_account.api.domain.records import ResourceRecord
from core_account.common.contracts import generated


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


def account_view(record: ResourceRecord) -> generated.Account:
    payload = _common(record)
    desired = record.desired
    payload["desired"] = {
        "lifecycle": record.lifecycle,
        "reconciliation": record.reconciliation,
        "platformAccess": desired["platformAccess"],
        "platformPermissions": desired["platformPermissions"],
        # Registro sem o campo (anterior à proteção) conta como protegido.
        "deletionProtection": desired.get("deletionProtection", True),
        **{field: desired[field] for field in PERSONAL_FIELDS if field in desired},
    }
    observed = _observed(record)
    if observed is not None:
        payload["observed"] = observed
    return generated.Account.model_validate(payload)
