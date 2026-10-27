"""Regras de negócio do usuário da Organization, aplicadas na admissão (decisões 0077 e 0098).

Puro: sem banco, rede ou relógio. O e-mail único na Organization e a cota de usuários por
Organization são declarados aqui (`unique_value`, `owner_quota`) e verificados na mesma transação
da admissão pelo adaptador do SSOT (`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_user.common.contracts import generated

PERSONAL_FIELDS = ("givenName", "familyName", "email")
"""Dados pessoais do `desired`: saem dele na remoção (`schemas/ipm/user/desired`)."""

LEGACY_DESIRED_FIELDS = ("permissions", "directPermissions")
"""Campos que o `desired` já teve e não tem mais (decisão 0097): as permissões efetivas são
calculadas pelo Controller. Registros gravados antes dela os descartam ao serem relidos."""


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre os usuários da Organization."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""

    scope_field: str
    scope_value: str


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de usuários por Organization, conferida na transação da admissão."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações da mesma Organization."""


def desired_for_create(specification: Mapping[str, Any]) -> dict[str, Any]:
    # A proteção contra exclusão nasce desligada no usuário da Organization (exceção à
    # decisão 0043, registrada na 0077). O `desired` guarda só a intenção: `roles` e `groups`.
    return {
        "lifecycle": "present",
        **specification,
        "roles": [str(role) for role in specification.get("roles", [])],
        "groups": [str(group) for group in specification.get("groups", [])],
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    kept = {key: value for key, value in current.items() if key not in LEGACY_DESIRED_FIELDS}
    return {
        **kept,
        **changes,
        "roles": [str(role) for role in changes.get("roles", current.get("roles", []))],
        "groups": [str(group) for group in changes.get("groups", current.get("groups", []))],
    }


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    # Com `lifecycle: absent`, o `desired` não carrega dados pessoais (schema `desired`).
    kept = {
        key: value
        for key, value in current.items()
        if key not in (*PERSONAL_FIELDS, *LEGACY_DESIRED_FIELDS)
    }
    return {**kept, "lifecycle": "absent"}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    """O e-mail é o nome de login: único dentro da Organization."""
    if desired["lifecycle"] != "present":
        return None
    email: str = desired["email"]
    organization_id: str = desired["organizationId"]
    return UniqueValue(
        field="email",
        value=email,
        lock_key=f"ipm.user.email:{organization_id}:{email}",
        scope_field="organizationId",
        scope_value=organization_id,
    )


def owner_quota(desired: Mapping[str, Any], limit: int | None) -> OwnerQuota | None:
    """Cota de usuários por Organization, só no create e só com limite do Receiver."""
    if limit is None:
        return None
    organization_id: str = desired["organizationId"]
    return OwnerQuota(
        field="organizationId",
        owner=organization_id,
        limit=limit,
        lock_key=f"ipm.user.organization:{organization_id}",
    )


def deletion_protected(current: Mapping[str, Any]) -> bool:
    return current.get("deletionProtection", False) is True


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    external = {key: value for key, value in desired.items() if key not in LEGACY_DESIRED_FIELDS}
    model = generated.UserDesiredData.model_validate({**external, "reconciliation": reconciliation})
    return model.model_dump(mode="json", exclude_none=True)
