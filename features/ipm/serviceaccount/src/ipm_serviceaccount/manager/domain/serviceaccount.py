"""Regras de negócio da service account da Organization, aplicadas pelo Manager (decisão 0094).

Puro: sem banco, rede ou relógio. O nome único na Organization e a cota de service accounts por
Organization são declarados aqui (`unique_value`, `owner_quota`) e verificados na mesma unidade
atômica do pedido pelo adaptador do SSOT (`docs/data/SSOT.md` §10.1). O `desired` guarda só
chaves **públicas** (com o fingerprint calculado pelo Receiver); a chave privada nunca chega ao
servidor.
"""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from ipm_serviceaccount.common.contracts import generated
from ipm_serviceaccount.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_serviceaccount.manager.domain.errors import PermanentMessageError
from ipm_serviceaccount.manager.domain.policy import OwnerQuota, Request, UniqueValue

LEGACY_DESIRED_FIELDS = ("permissions",)
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


def _keys(values: list[generated.ServiceAccountDesiredKey]) -> list[dict[str, Any]]:
    """Chaves públicas no formato do `desired`, ordenadas pelo fingerprint (estável)."""
    dumped = [value.model_dump(mode="json", by_alias=True) for value in values]
    return sorted(dumped, key=lambda key: str(key["fingerprint"]))


def key_fingerprints(keys: object) -> list[str]:
    """Fingerprints de uma lista de chaves de `desired` ou `observed`, ordenados."""
    if not isinstance(keys, list):
        return []
    return sorted(
        str(cast("dict[str, Any]", key).get("fingerprint", ""))
        for key in cast("list[object]", keys)
        if isinstance(key, dict)
    )


class ServiceAccountPolicy:
    """Service account da Organization: nome único nela, Organization imutável e cota por ela."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.ServiceAccountRequestedCreateData, data, label="requested/create"
                )
                specification = create.specification
                spec_dict: dict[str, Any] = {
                    "organizationId": specification.organization_id,
                    "name": specification.name,
                    "roles": _roles(specification.roles),
                    # A proteção contra exclusão nasce ligada na identidade de máquina (0094).
                    "deletionProtection": specification.deletion_protection is not False,
                    "keys": _keys(specification.keys),
                }
                if specification.description is not None:
                    spec_dict["description"] = specification.description
                return Request(
                    "create",
                    create.operation_id,
                    create.request_digest,
                    specification=spec_dict,
                    organization_quota_limit=create.organization_quota_limit,
                )
            case "update":
                update = _validated(
                    generated.ServiceAccountRequestedUpdateData, data, label="requested/update"
                )
                changes: dict[str, Any] = {}
                if update.specification is not None:
                    if update.specification.description is not None:
                        changes["description"] = update.specification.description
                    if update.specification.roles is not None:
                        changes["roles"] = _roles(update.specification.roles)
                    if update.specification.deletion_protection is not None:
                        changes["deletionProtection"] = update.specification.deletion_protection
                    if update.specification.keys is not None:
                        changes["keys"] = _keys(update.specification.keys)
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
                    generated.ServiceAccountRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(
                    f"operação não suportada para serviceaccount: {operation}"
                )

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        # O `desired` guarda só a intenção: `roles`. As permissões efetivas são do Controller.
        spec = dict(request.specification)
        return {
            "lifecycle": "present",
            **spec,
            "roles": [str(role) for role in spec.get("roles", [])],
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        spec = dict(request.specification or {})
        kept = {key: value for key, value in current.items() if key not in LEGACY_DESIRED_FIELDS}
        return {
            **kept,
            **spec,
            "roles": [str(role) for role in spec.get("roles", current.get("roles", []))],
        }

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        # Com `lifecycle: absent`, o `desired` deixa de carregar as chaves públicas.
        kept = {
            key: value
            for key, value in current.items()
            if key not in ("keys", *LEGACY_DESIRED_FIELDS)
        }
        return {**kept, "lifecycle": "absent", "keys": []}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
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

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        """Sem regra de valor recusado: as permissões efetivas não fazem parte do `desired`."""
        _ = desired
        return False

    def owner_quota(self, request: Request, desired: Mapping[str, Any]) -> OwnerQuota | None:
        """Cota de service accounts por Organization, só no create e só com limite do Receiver.

        O Receiver não define limite para o operador (decisão 0094).
        """
        if request.operation != "create" or request.organization_quota_limit is None:
            return None
        organization_id: str = desired["organizationId"]
        return OwnerQuota(
            field="organizationId",
            owner=organization_id,
            limit=request.organization_quota_limit,
            lock_key=f"ipm.serviceaccount.organization:{organization_id}",
        )

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        # Na service account a proteção nasce ligada: ausente vale `true` (decisão 0094).
        return current.get("deletionProtection", True) is not False

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.ServiceAccountDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)
