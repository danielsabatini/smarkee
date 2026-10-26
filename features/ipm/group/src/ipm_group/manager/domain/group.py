"""Regras de negócio do Grupo de usuários da Organization, aplicadas pelo Manager (decisão 0088).

Puro: sem banco, rede ou relógio. O nome único na Organization, as roles fora do catálogo e a
cota de grupos por Organization são declarados aqui (`unique_value`, `invalid`, `owner_quota`) e
verificados na mesma unidade atômica do pedido pelo adaptador do SSOT (`docs/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.contracts import generated
from ipm_group.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_group.manager.domain.errors import PermanentMessageError
from ipm_group.manager.domain.policy import OwnerQuota, Request, UniqueValue


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


def _roles(values: list[generated.RoleName] | None) -> list[str]:
    return sorted({role.root for role in values or []})


class GroupPolicy:
    """Grupo da Organization: nome único nela, imutável e cota por Organization."""

    def __init__(self, catalog: RolesCatalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else RolesCatalog()

    @property
    def catalog(self) -> RolesCatalog:
        return self._catalog

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.GroupRequestedCreateData, data, label="requested/create"
                )
                specification = create.specification
                spec_dict: dict[str, Any] = {
                    "organizationId": specification.organization_id,
                    "name": str(specification.name).strip(),
                    "description": str(specification.description).strip(),
                    "roles": _roles(specification.roles),
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
                    generated.GroupRequestedUpdateData, data, label="requested/update"
                )
                changes: dict[str, Any] = {}
                if update.specification is not None:
                    if update.specification.description is not None:
                        changes["description"] = str(update.specification.description).strip()
                    if update.specification.roles is not None:
                        changes["roles"] = _roles(update.specification.roles)
                    if update.specification.deletion_protection is not None:
                        changes["deletionProtection"] = update.specification.deletion_protection
                reconciliation = (
                    update.reconciliation.value if update.reconciliation is not None else None
                )
                if not changes and reconciliation is None:
                    raise PermanentMessageError(
                        "requested de update exige specification ou reconciliation"
                    )
                return Request(
                    "update",
                    update.operation_id,
                    update.request_digest,
                    resource_version=_parse_resource_version(update.resource_version),
                    specification=changes or None,
                    reconciliation=reconciliation,
                )
            case "delete":
                delete = _validated(
                    generated.GroupRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(f"operação não suportada para group: {operation}")

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        del requested_by
        assert request.specification is not None  # noqa: S101
        spec = dict(request.specification)
        roles = [str(r) for r in spec.get("roles", [])]
        return {
            "lifecycle": "present",
            **spec,
            "roles": roles,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        spec = dict(request.specification or {})
        roles = [str(r) for r in spec.get("roles", current.get("roles", []))]
        return {
            **current,
            **spec,
            "roles": roles,
        }

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return {**current, "lifecycle": "absent"}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        """O slug do grupo é único dentro da Organization."""
        if desired.get("lifecycle") != "present":
            return None
        name: str = desired["name"]
        organization_id: str = desired["organizationId"]
        return UniqueValue(
            field="name",
            value=name,
            lock_key=f"ipm.group.name:{organization_id}:{name}",
            scope_field="organizationId",
            scope_value=organization_id,
        )

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        """Role fora do catálogo: não pode ser atribuída."""
        roles: list[str] = desired.get("roles", [])
        organization_id = str(desired.get("organizationId") or "")
        return bool(self._catalog.outside_catalog(roles, organization_id))

    def owner_quota(self, request: Request, desired: Mapping[str, Any]) -> OwnerQuota | None:
        """Cota de grupos por Organization, só no create e só com limite do Receiver."""
        if request.operation != "create" or request.organization_quota_limit is None:
            return None
        organization_id: str = desired["organizationId"]
        return OwnerQuota(
            field="organizationId",
            owner=organization_id,
            limit=request.organization_quota_limit,
            lock_key=f"ipm.group.organization:{organization_id}",
        )

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        return current.get("deletionProtection", False) is True

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.GroupDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        if desired.get("lifecycle") == "absent":
            return presence == "absent"
        if presence != "present" or observed is None:
            return False
        return (
            observed.get("name") == desired.get("name")
            and observed.get("description") == desired.get("description")
            and sorted(observed.get("roles") or []) == sorted(desired.get("roles") or [])
            and (observed.get("deletionProtection") is True)
            == (desired.get("deletionProtection", False) is True)
        )
