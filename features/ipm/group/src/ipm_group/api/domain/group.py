"""Regras de negócio do Grupo da Organization, aplicadas na admissão (decisões 0088 e 0098).

Puro: sem banco, rede ou relógio. O nome único na Organization e a cota de grupos por Organization
são declarados aqui (`unique_value`, `owner_quota`) e verificados na mesma transação da admissão
pelo adaptador do SSOT (`docs/data/SSOT.md` §10.1). As roles dentro do catálogo e o `bind` são
conferidos na camada HTTP (`domain/access.py`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_group.common.contracts import generated


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre os Grupos ativos (`lifecycle = present`)."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""

    scope_field: str
    scope_value: str
    """Campo e valor que delimitam a unicidade (a Organization do Grupo)."""


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de Grupos por Organization, conferida na transação da admissão."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações da mesma Organization."""


def desired_for_create(specification: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lifecycle": "present",
        "organizationId": specification["organizationId"],
        "name": specification["name"],
        "description": specification["description"],
        "roles": [str(role) for role in specification.get("roles", [])],
        "deletionProtection": specification.get("deletionProtection") is True,
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(current)
    for key in ("description", "roles", "deletionProtection"):
        if key in changes:
            updated[key] = [str(role) for role in changes[key]] if key == "roles" else changes[key]
    return updated


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, "lifecycle": "absent"}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    """O slug do grupo é único dentro da Organization."""
    if desired.get("lifecycle") != "present":
        return None
    name = str(desired["name"])
    organization_id = str(desired["organizationId"])
    return UniqueValue(
        field="name",
        value=name,
        lock_key=f"ipm.group.name:{organization_id}:{name}",
        scope_field="organizationId",
        scope_value=organization_id,
    )


def owner_quota(desired: Mapping[str, Any], limit: int | None) -> OwnerQuota | None:
    """Cota de Grupos por Organization, só no create e só com limite (operador não tem)."""
    if limit is None:
        return None
    organization_id = str(desired["organizationId"])
    return OwnerQuota(
        field="organizationId",
        owner=organization_id,
        limit=limit,
        lock_key=f"ipm.group.organization:{organization_id}",
    )


def deletion_protected(current: Mapping[str, Any]) -> bool:
    return current.get("deletionProtection", False) is True


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    return generated.GroupDesiredData.model_validate(
        {**desired, "reconciliation": reconciliation}
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
