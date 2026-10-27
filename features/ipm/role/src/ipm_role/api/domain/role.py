"""Regras de negócio da Role, aplicadas na admissão (decisões 0083, 0092 e 0098).

Puro: sem banco, rede ou relógio. A unicidade de `name` entre Roles ativas (`lifecycle = present`)
é por Organization **e** contra as predefinidas da plataforma (`core`): é declarada aqui
(`unique_value`) e verificada na mesma transação da admissão pelo adaptador do SSOT
(`docs/data/SSOT.md` §10.1). A cota de Roles `custom` por Organization segue o mesmo caminho
(`owner_quota`, decisão 0092).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_role.common.contracts import generated

CUSTOM_ROLE_TYPE = "custom"
"""Natureza da Role criada via API; as `predefined` nascem do bootstrap."""

PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles `predefined`. Reservada: nenhuma `custom` nasce nela."""


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre as Roles ativas."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""

    scope_field: str
    scope_values: tuple[str, ...]
    """Campo e valores que delimitam a unicidade (a Organization da Role e `core`)."""


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de Roles `custom` por Organization, conferida na transação da admissão."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações da mesma Organization."""


def organization_of(desired: Mapping[str, Any]) -> str:
    """Organization dona da Role; a ausência (dado anterior à decisão 0092) vale `core`."""
    return str(desired.get("organizationId") or PLATFORM_ORGANIZATION_ID)


def desired_for_create(specification: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lifecycle": "present",
        "organizationId": specification["organizationId"],
        "name": specification["name"],
        "roleType": CUSTOM_ROLE_TYPE,
        "description": specification["description"],
        "permissions": list(specification["permissions"]),
        "deletionProtection": True,  # todo recurso apagável nasce protegido (decisão 0043)
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(current)
    for key in ("description", "permissions", "deletionProtection"):
        if key in changes:
            updated[key] = list(changes[key]) if key == "permissions" else changes[key]
    return updated


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, "lifecycle": "absent"}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    if desired.get("lifecycle") != "present":
        return None
    name = str(desired["name"])
    organization_id = organization_of(desired)
    # Uma `custom` não pode repetir o nome de uma predefinida (`core`); as predefinidas só
    # conferem entre si.
    scope = (organization_id, PLATFORM_ORGANIZATION_ID)
    return UniqueValue(
        field="name",
        value=name,
        lock_key=f"ipm.role.name:{organization_id}:{name}",
        scope_field="organizationId",
        scope_values=tuple(dict.fromkeys(scope)),
    )


def owner_quota(desired: Mapping[str, Any], limit: int | None) -> OwnerQuota | None:
    """Cota de Roles `custom` por Organization, só no create e só com limite (operador não tem)."""
    if limit is None:
        return None
    organization_id = organization_of(desired)
    return OwnerQuota(
        field="organizationId",
        owner=organization_id,
        limit=limit,
        lock_key=f"ipm.role.organization:{organization_id}",
    )


def has_no_permissions(desired: Mapping[str, Any]) -> bool:
    """Uma Role sem permissões não é admitida."""
    permissions = desired.get("permissions")
    return not isinstance(permissions, list) or not permissions


def deletion_protected(current: Mapping[str, Any]) -> bool:
    return current.get("deletionProtection", True) is not False


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    return generated.RoleDesiredData.model_validate(
        {
            "lifecycle": desired["lifecycle"],
            "reconciliation": reconciliation,
            "organizationId": organization_of(desired),
            "name": desired["name"],
            "roleType": desired.get("roleType", CUSTOM_ROLE_TYPE),
            "description": desired["description"],
            "permissions": desired["permissions"],
            "deletionProtection": deletion_protected(desired),
        }
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
