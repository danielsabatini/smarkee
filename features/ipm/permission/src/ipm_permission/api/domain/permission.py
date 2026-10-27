"""Regras de negócio da Permission, aplicadas na admissão (decisões 0083 e 0098).

Puro: sem banco, rede ou relógio. A unicidade global de `name` entre Permissions ativas (`lifecycle
= present`) é declarada aqui (`unique_value`) e verificada na mesma transação da admissão pelo
adaptador do SSOT (`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_permission.common.contracts import generated


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre as Permissions ativas."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""


def desired_for_create(specification: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lifecycle": "present",
        "name": specification["name"],
        "description": specification["description"],
        "grantable": bool(specification["grantable"]),
        "deletionProtection": True,  # todo recurso apagável nasce protegido (decisão 0043)
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, **changes}


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, "lifecycle": "absent"}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    if desired["lifecycle"] != "present":
        return None
    name = str(desired["name"])
    return UniqueValue(field="name", value=name, lock_key=f"ipm.permission:name:{name}")


def description_repeats_name(description: str, name: str) -> bool:
    """A descrição deve descrever a ação e não repetir a chave."""
    return description.strip() == name.strip()


def deletion_protected(current: Mapping[str, Any]) -> bool:
    return current.get("deletionProtection", True) is not False


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    model = generated.PermissionDesiredData.model_validate(
        {
            "lifecycle": desired["lifecycle"],
            "reconciliation": reconciliation,
            "name": desired["name"],
            "description": desired["description"],
            "grantable": bool(desired.get("grantable", False)),
            "deletionProtection": deletion_protected(desired),
        }
    )
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
