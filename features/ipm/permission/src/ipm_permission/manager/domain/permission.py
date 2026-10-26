"""Regras de negócio da Permission, aplicadas pelo Manager (decisão 0083).

Puro: sem banco, rede ou relógio. A unicidade global de `name` entre Permissions ativas (`lifecycle
= present`) é declarada aqui (`unique_value`) e verificada na mesma unidade atômica do pedido pelo
adaptador do SSOT (`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_permission.common.contracts import generated
from ipm_permission.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_permission.manager.domain.errors import PermanentMessageError
from ipm_permission.manager.domain.policy import Request, UniqueValue


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


def module_of(permission_name: str) -> str:
    """Extrai o módulo (`<módulo>`) da chave `<módulo>.<tipo>.<ação>`."""
    return permission_name.split(".", 1)[0]


class PermissionPolicy:
    """Política de `ipm.permission`."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        if operation == "create":
            parsed = _validated(
                generated.PermissionRequestedCreateData, data, label="requested de create"
            )
            specification = {
                "name": parsed.specification.name.strip(),
                "description": parsed.specification.description.strip(),
                "grantable": bool(parsed.specification.grantable),
            }
            return Request(
                operation="create",
                operation_id=str(parsed.operation_id),
                request_digest=parsed.request_digest,
                specification=specification,
            )
        if operation == "update":
            parsed = _validated(
                generated.PermissionRequestedUpdateData, data, label="requested de update"
            )
            update_specification: dict[str, Any] = {}
            if parsed.specification is not None:
                if parsed.specification.description is not None:
                    update_specification["description"] = parsed.specification.description.strip()
                if parsed.specification.grantable is not None:
                    update_specification["grantable"] = bool(parsed.specification.grantable)
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
                generated.PermissionRequestedDeleteData, data, label="requested de delete"
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
            "name": request.specification["name"],
            "description": request.specification["description"],
            "grantable": bool(request.specification["grantable"]),
            "deletionProtection": True,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        updated = dict(current)
        if request.specification:
            if "description" in request.specification:
                updated["description"] = request.specification["description"]
            if "grantable" in request.specification:
                updated["grantable"] = bool(request.specification["grantable"])
            if "deletionProtection" in request.specification:
                updated["deletionProtection"] = request.specification["deletionProtection"]
        return updated

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return {**current, "lifecycle": "absent"}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        if desired.get("lifecycle") != "present":
            return None
        name = str(desired["name"])
        return UniqueValue(
            field="name",
            value=name,
            lock_key=f"ipm.permission:name:{name}",
        )

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        name = str(desired.get("name", "")).strip()
        description = str(desired.get("description", "")).strip()
        return not name or not description or description == name

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        return current.get("deletionProtection", True) is not False

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        return generated.PermissionDesiredData.model_validate(
            {
                "lifecycle": desired["lifecycle"],
                "reconciliation": reconciliation,
                "name": desired["name"],
                "description": desired["description"],
                "grantable": bool(desired.get("grantable", False)),
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
        name = str(desired["name"])
        return (
            observed.get("name") == name
            and observed.get("description") == desired["description"]
            and observed.get("group") == module_of(name)
        )
