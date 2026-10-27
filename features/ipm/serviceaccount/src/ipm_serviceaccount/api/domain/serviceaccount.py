"""Regras de negócio da service account da Organization, aplicadas na admissão (decisão 0098).

Puro: sem banco, rede ou relógio. O nome único na Organization e a cota de service accounts por
Organization são declarados aqui (`unique_value`, `owner_quota`) e verificados na mesma transação
da admissão pelo adaptador do SSOT (`docs/data/SSOT.md` §10.1). O `desired` guarda só chaves
**públicas** (com o fingerprint calculado pela API); a chave privada nunca chega ao servidor.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_serviceaccount.common.contracts import generated

LEGACY_DESIRED_FIELDS = ("permissions",)
"""Campos que o `desired` já teve e não tem mais (decisão 0097): as permissões efetivas são
calculadas pelo Controller. Registros gravados antes dela os descartam ao serem relidos."""


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre as service accounts da Organization."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""

    scope_field: str
    scope_value: str


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de service accounts por Organization, conferida na transação da admissão."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações da mesma Organization."""


def desired_for_create(specification: Mapping[str, Any]) -> dict[str, Any]:
    # O `desired` guarda só a intenção: `roles`. As permissões efetivas são do Controller.
    return {
        "lifecycle": "present",
        **specification,
        "roles": [str(role) for role in specification.get("roles", [])],
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    kept = {key: value for key, value in current.items() if key not in LEGACY_DESIRED_FIELDS}
    return {
        **kept,
        **changes,
        "roles": [str(role) for role in changes.get("roles", current.get("roles", []))],
    }


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    # Com `lifecycle: absent`, o `desired` deixa de carregar as chaves públicas.
    kept = {
        key: value for key, value in current.items() if key not in ("keys", *LEGACY_DESIRED_FIELDS)
    }
    return {**kept, "lifecycle": "absent", "keys": []}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    """O nome é único dentro da Organization (entre as service accounts ativas)."""
    if desired["lifecycle"] != "present":
        return None
    name: str = desired["name"]
    organization_id: str = desired["organizationId"]
    return UniqueValue(
        field="name",
        value=name,
        lock_key=f"ipm.serviceaccount.name:{organization_id}:{name}",
        scope_field="organizationId",
        scope_value=organization_id,
    )


def owner_quota(desired: Mapping[str, Any], limit: int | None) -> OwnerQuota | None:
    """Cota por Organization, só no create e só com limite (o operador não tem, decisão 0094)."""
    if limit is None:
        return None
    organization_id: str = desired["organizationId"]
    return OwnerQuota(
        field="organizationId",
        owner=organization_id,
        limit=limit,
        lock_key=f"ipm.serviceaccount.organization:{organization_id}",
    )


def deletion_protected(current: Mapping[str, Any]) -> bool:
    # Na service account a proteção nasce ligada: ausente vale `true` (decisão 0094).
    return current.get("deletionProtection", True) is not False


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    model = generated.ServiceAccountDesiredData.model_validate(
        {**desired, "reconciliation": reconciliation}
    )
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
