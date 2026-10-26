"""Regras de negócio da Role, aplicadas pelo Manager (decisão 0083).

Puro: sem banco, rede ou relógio. A unicidade de `name` entre Roles ativas (`lifecycle = present`)
é por Organization **e** contra as predefinidas da plataforma (`core`): é declarada aqui
(`unique_value`) e verificada na mesma unidade atômica do pedido pelo adaptador do SSOT
(`docs/data/SSOT.md` §10.1). A cota de Roles `custom` por Organization segue o mesmo caminho
(`owner_quota`, decisão 0092).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_role.common.contracts import generated
from ipm_role.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_role.manager.domain.errors import PermanentMessageError
from ipm_role.manager.domain.policy import OwnerQuota, Request, UniqueValue

CUSTOM_ROLE_TYPE = "custom"
"""Natureza da Role criada por pedido via API; as `predefined` nascem do bootstrap."""

PLATFORM_ORGANIZATION_ID = "core"
"""Organization de sistema, dona das Roles `predefined`. Reservada: nenhuma `custom` nasce nela."""


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


def _permissions(items: list[generated.Permission], *, label: str) -> list[str]:
    values = [str(item.root).strip() for item in items if str(item.root).strip()]
    if not values:
        raise PermanentMessageError(f"{label} inválido nos campos: ['specification.permissions']")
    return sorted(set(values))


def _organization_of(desired: Mapping[str, Any]) -> str:
    """Organization dona da Role; a ausência (dado anterior à decisão 0092) vale `core`."""
    return str(desired.get("organizationId") or PLATFORM_ORGANIZATION_ID)


class RolePolicy:
    """Política de `ipm.role`."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        if operation == "create":
            parsed = _validated(
                generated.RoleRequestedCreateData, data, label="requested de create"
            )
            organization_id = parsed.specification.organization_id.strip()
            if organization_id == PLATFORM_ORGANIZATION_ID:
                raise PermanentMessageError(
                    "requested de create inválido nos campos: ['specification.organizationId']"
                )
            specification = {
                "organizationId": organization_id,
                "name": parsed.specification.name.strip(),
                "description": parsed.specification.description.strip(),
                "permissions": _permissions(
                    parsed.specification.permissions, label="requested de create"
                ),
            }
            return Request(
                operation="create",
                operation_id=str(parsed.operation_id),
                request_digest=parsed.request_digest,
                specification=specification,
                organization_quota_limit=parsed.organization_quota_limit,
            )
        if operation == "update":
            parsed = _validated(
                generated.RoleRequestedUpdateData, data, label="requested de update"
            )
            update_specification: dict[str, Any] = {}
            if parsed.specification is not None:
                if parsed.specification.description is not None:
                    update_specification["description"] = parsed.specification.description.strip()
                if parsed.specification.permissions is not None:
                    update_specification["permissions"] = _permissions(
                        parsed.specification.permissions, label="requested de update"
                    )
                if parsed.specification.deletion_protection is not None:
                    update_specification["deletionProtection"] = (
                        parsed.specification.deletion_protection
                    )
            reconciliation = (
                parsed.reconciliation.value if parsed.reconciliation is not None else None
            )
            if not update_specification and reconciliation is None:
                raise PermanentMessageError(
                    "requested de update exige specification ou reconciliation"
                )
            return Request(
                operation="update",
                operation_id=str(parsed.operation_id),
                request_digest=parsed.request_digest,
                resource_version=_parse_resource_version(parsed.resource_version),
                specification=update_specification or None,
                reconciliation=reconciliation,
            )
        if operation == "delete":
            parsed = _validated(
                generated.RoleRequestedDeleteData, data, label="requested de delete"
            )
            return Request(
                operation="delete",
                operation_id=str(parsed.operation_id),
                request_digest=parsed.request_digest,
                resource_version=_parse_resource_version(parsed.resource_version),
            )
        raise PermanentMessageError(f"operação inválida: {operation!r}")

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        del requested_by
        if request.specification is None:
            raise PermanentMessageError("create sem specification")
        return {
            "lifecycle": "present",
            "organizationId": request.specification["organizationId"],
            "name": request.specification["name"],
            "roleType": CUSTOM_ROLE_TYPE,
            "description": request.specification["description"],
            "permissions": list(request.specification["permissions"]),
            "deletionProtection": True,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        updated = dict(current)
        if request.specification:
            if "description" in request.specification:
                updated["description"] = request.specification["description"]
            if "permissions" in request.specification:
                updated["permissions"] = list(request.specification["permissions"])
            if "deletionProtection" in request.specification:
                updated["deletionProtection"] = request.specification["deletionProtection"]
        return updated

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return {**current, "lifecycle": "absent"}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        if desired.get("lifecycle") != "present":
            return None
        name = str(desired["name"])
        organization_id = _organization_of(desired)
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

    def owner_quota(self, request: Request, desired: Mapping[str, Any]) -> OwnerQuota | None:
        """Cota de Roles `custom` por Organization, só no create e só com limite do Receiver."""
        if request.operation != "create" or request.organization_quota_limit is None:
            return None
        organization_id = _organization_of(desired)
        return OwnerQuota(
            field="organizationId",
            owner=organization_id,
            limit=request.organization_quota_limit,
            lock_key=f"ipm.role.organization:{organization_id}",
        )

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        permissions = desired.get("permissions")
        return not isinstance(permissions, list) or not permissions

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        return current.get("deletionProtection", True) is not False

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        return generated.RoleDesiredData.model_validate(
            {
                "lifecycle": desired["lifecycle"],
                "reconciliation": reconciliation,
                "organizationId": _organization_of(desired),
                "name": desired["name"],
                "roleType": desired.get("roleType", CUSTOM_ROLE_TYPE),
                "description": desired["description"],
                "permissions": desired["permissions"],
                "deletionProtection": self.deletion_protected(desired),
            }
        ).model_dump(mode="json", by_alias=True, exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        if presence != "present" or observed is None:
            return False
        return (
            observed.get("name") == desired["name"]
            and observed.get("description") == desired["description"]
            and observed.get("permissions") == desired["permissions"]
            and observed.get("deletionProtection") == self.deletion_protected(desired)
        )
