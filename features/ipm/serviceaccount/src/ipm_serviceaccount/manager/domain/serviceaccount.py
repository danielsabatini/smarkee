"""Regras de negócio da service account da Organization, aplicadas pelo Manager (decisão 0094).

Puro: sem banco, rede ou relógio. O nome único na Organization, as permissões fora do módulo e a
cota de service accounts por Organization são declarados aqui (`unique_value`, `invalid`,
`owner_quota`) e verificados na mesma unidade atômica do pedido pelo adaptador do SSOT
(`docs/data/SSOT.md` §10.1). O `desired` guarda só chaves **públicas** (com o fingerprint calculado
pelo Receiver); a chave privada nunca chega ao servidor.
"""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from ipm_serviceaccount.common.catalog import AccessCatalog
from ipm_serviceaccount.common.contracts import generated
from ipm_serviceaccount.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_serviceaccount.manager.domain.errors import PermanentMessageError
from ipm_serviceaccount.manager.domain.policy import OwnerQuota, Request, UniqueValue

PERMISSION_MODULE_PREFIX = "ipm."
"""O Executor só concede permissões do projeto `roles-ipm` (o Project Grant da Organization)."""


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

    def __init__(self, catalog: AccessCatalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else AccessCatalog()

    @property
    def catalog(self) -> AccessCatalog:
        return self._catalog

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

    def _effective(self, organization_id: str, roles: list[str]) -> list[str]:
        return self._catalog.expand_roles(roles, organization_id)

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        spec = dict(request.specification)
        organization_id = str(spec.get("organizationId", ""))
        roles = [str(role) for role in spec.get("roles", [])]
        return {
            "lifecycle": "present",
            **spec,
            "roles": roles,
            "permissions": self._effective(organization_id, roles),
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        spec = dict(request.specification or {})
        organization_id = str(current.get("organizationId", ""))
        roles = [str(role) for role in spec.get("roles", current.get("roles", []))]
        return {
            **current,
            **spec,
            "roles": roles,
            "permissions": self._effective(organization_id, roles),
        }

    def rolled_out(self, current: Mapping[str, Any]) -> dict[str, Any] | None:
        """Re-expande `permissions` quando uma `ipm.role` ou `ipm.permission` muda (0083)."""
        if current.get("lifecycle") != "present":
            return None
        roles = [str(role) for role in cast("list[Any]", current.get("roles") or [])]
        if not roles:
            return None
        effective = self._effective(str(current.get("organizationId", "")), roles)
        if current.get("permissions") == effective:
            return None
        return {**current, "permissions": effective}

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        # Com `lifecycle: absent`, o `desired` deixa de carregar as chaves públicas.
        kept = {key: value for key, value in current.items() if key != "keys"}
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
        """Permissão fora do módulo `ipm`: o Executor não a concederia (o Receiver recusa antes)."""
        permissions: list[str] = desired.get("permissions", [])
        return any(
            not permission.startswith(PERMISSION_MODULE_PREFIX) for permission in permissions
        )

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

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        # Campos gerenciados: `lifecycle`, `permissions`, `description`, `deletionProtection` e
        # `keys` (por fingerprint; chave vencida continua listada como `expired`). A Organization
        # e o nome são imutáveis e definidos na criação (schemas/ipm/serviceaccount/desired).
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        return (
            presence == "present"
            and observed is not None
            and sorted(observed.get("permissions") or [])
            == sorted(desired.get("permissions") or [])
            and observed.get("deletionProtection") == self.deletion_protected(desired)
            and (observed.get("description") or None) == (desired.get("description") or None)
            and key_fingerprints(observed.get("keys")) == key_fingerprints(desired.get("keys"))
        )
