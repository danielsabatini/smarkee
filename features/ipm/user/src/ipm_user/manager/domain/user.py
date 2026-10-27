"""Regras de negócio do usuário da Organization, aplicadas pelo Manager (decisão 0077).

Puro: sem banco, rede ou relógio. O e-mail único na Organization e a cota de usuários por
Organization são declarados aqui (`unique_value`, `owner_quota`) e verificados na mesma unidade
atômica do pedido pelo adaptador do SSOT (`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_user.common.contracts import generated
from ipm_user.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_user.manager.domain.errors import PermanentMessageError
from ipm_user.manager.domain.policy import OwnerQuota, Request, UniqueValue

PERSONAL_FIELDS = ("givenName", "familyName", "email")
"""Dados pessoais do `desired`: saem dele na remoção (`schemas/ipm/user/desired`)."""

LEGACY_DESIRED_FIELDS = ("permissions", "directPermissions")
"""Campos que o `desired` já teve e não tem mais (decisão 0097): as permissões efetivas são
calculadas pelo Controller. Registros gravados antes dela os descartam ao serem relidos."""


def _validated[M: ContractModel](model: type[M], data: Mapping[str, Any], *, label: str) -> M:
    try:
        return validate_tolerant(model, data)
    except ValidationError as error:
        raise PermanentMessageError(f"{label} inválido nos campos: {fields_of(error)}") from None


def _parse_resource_version(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise PermanentMessageError("resourceVersion não numérico") from None


def _roles(values: list[generated.RoleName] | set[str] | None) -> list[str]:
    if values is None:
        return []
    return sorted({getattr(role, "root", str(role)) for role in values})


def _groups(values: list[generated.GroupName] | set[str] | None) -> list[str]:
    if values is None:
        return []
    return sorted({getattr(group, "root", str(group)) for group in values})


class UserPolicy:
    """Usuário da Organization: e-mail único nela, Organization imutável e cota por Organization."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.UserRequestedCreateData, data, label="requested/create"
                )
                specification = create.specification
                spec_dict: dict[str, Any] = {
                    "organizationId": specification.organization_id,
                    "givenName": specification.given_name,
                    "familyName": specification.family_name,
                    "email": str(specification.email).strip().lower(),
                    "roles": _roles(specification.roles),
                    "groups": _groups(specification.groups),
                    "deletionProtection": specification.deletion_protection is True,
                }
                return Request(
                    "create",
                    create.operation_id,
                    create.request_digest,
                    specification=spec_dict,
                    organization_quota_limit=create.organization_quota_limit,
                )
            case "update":
                update = _validated(
                    generated.UserRequestedUpdateData, data, label="requested/update"
                )
                changes: dict[str, Any] = {}
                if update.specification is not None:
                    if update.specification.roles is not None:
                        changes["roles"] = _roles(update.specification.roles)
                    if update.specification.groups is not None:
                        changes["groups"] = _groups(update.specification.groups)
                    if update.specification.deletion_protection is not None:
                        changes["deletionProtection"] = update.specification.deletion_protection
                return Request(
                    "update",
                    update.operation_id,
                    update.request_digest,
                    resource_version=_parse_resource_version(update.resource_version),
                    specification=changes,
                    reconciliation=update.reconciliation.value if update.reconciliation else None,
                )
            case "delete":
                delete = _validated(
                    generated.UserRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(f"operação não suportada para user: {operation}")

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        # A proteção contra exclusão nasce desligada no usuário da Organization (exceção à
        # decisão 0043, registrada na 0077). O `desired` guarda só a intenção: `roles` e `groups`.
        spec = dict(request.specification)
        return {
            "lifecycle": "present",
            **spec,
            "roles": [str(role) for role in spec.get("roles", [])],
            "groups": [str(group) for group in spec.get("groups", [])],
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        spec = dict(request.specification or {})
        kept = {key: value for key, value in current.items() if key not in LEGACY_DESIRED_FIELDS}
        return {
            **kept,
            **spec,
            "roles": [str(role) for role in spec.get("roles", current.get("roles", []))],
            "groups": [str(group) for group in spec.get("groups", current.get("groups", []))],
        }

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        # Com `lifecycle: absent`, o `desired` não carrega dados pessoais (schema `desired`).
        kept = {
            key: value
            for key, value in current.items()
            if key not in (*PERSONAL_FIELDS, *LEGACY_DESIRED_FIELDS)
        }
        return {**kept, "lifecycle": "absent"}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
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

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        """Sem regra de valor recusado: as permissões efetivas não fazem parte do `desired`."""
        _ = desired
        return False

    def owner_quota(self, request: Request, desired: Mapping[str, Any]) -> OwnerQuota | None:
        """Cota de usuários por Organization, só no create e só com limite do Receiver.

        O Receiver não define limite para o operador (decisão 0077).
        """
        if request.operation != "create" or request.organization_quota_limit is None:
            return None
        organization_id: str = desired["organizationId"]
        return OwnerQuota(
            field="organizationId",
            owner=organization_id,
            limit=request.organization_quota_limit,
            lock_key=f"ipm.user.organization:{organization_id}",
        )

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        return current.get("deletionProtection", False) is True

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        external = {
            key: value for key, value in desired.items() if key not in LEGACY_DESIRED_FIELDS
        }
        model = generated.UserDesiredData.model_validate(
            {**external, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)
