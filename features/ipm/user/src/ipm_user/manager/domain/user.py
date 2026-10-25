"""Regras de negócio do usuário da Organization, aplicadas pelo Manager (decisão 0077).

Puro: sem banco, rede ou relógio. O e-mail único na Organization, as permissões fora do módulo e a
cota de usuários por Organization são declarados aqui (`unique_value`, `invalid`, `owner_quota`) e
verificados na mesma unidade atômica do pedido pelo adaptador do SSOT (`docs/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from ipm_user.common.catalog import AccessCatalog
from ipm_user.common.contracts import generated
from ipm_user.common.contracts.base import ContractModel, fields_of, validate_tolerant
from ipm_user.manager.domain.errors import PermanentMessageError
from ipm_user.manager.domain.policy import OwnerQuota, Request, UniqueValue

PERSONAL_FIELDS = ("givenName", "familyName", "email")
"""Dados pessoais do `desired`: saem dele na remoção (`schemas/ipm/user/desired`)."""

INTERNAL_DESIRED_FIELDS = ("directPermissions",)
"""Campos internos do `desired` no SSOT para re-expansão de Roles; não saem na mensageria."""

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


def _permissions(values: list[generated.Permission] | None) -> list[str]:
    return sorted({permission.root for permission in values or []})


def _roles(values: list[generated.RoleName] | None) -> list[str]:
    return sorted({role.root for role in values or []})


class UserPolicy:
    """Usuário da Organization: e-mail único nela, Organization imutável e cota por Organization."""

    def __init__(self, catalog: AccessCatalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else AccessCatalog()

    @property
    def catalog(self) -> AccessCatalog:
        return self._catalog

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
                    "permissions": _permissions(specification.permissions),
                    "deletionProtection": specification.deletion_protection is True,
                }
                if specification.roles is not None:
                    spec_dict["roles"] = _roles(specification.roles)
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
                    if update.specification.permissions is not None:
                        changes["permissions"] = _permissions(update.specification.permissions)
                    if update.specification.roles is not None:
                        changes["roles"] = _roles(update.specification.roles)
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
        # decisão 0043, registrada na 0077).
        spec = dict(request.specification)
        if "roles" not in spec:
            return {"lifecycle": "present", **spec}
        direct = [str(p) for p in spec.get("permissions", [])]
        roles = [str(r) for r in spec["roles"]]
        effective = self._catalog.effective_permissions(direct, roles)
        return {
            "lifecycle": "present",
            **spec,
            "directPermissions": direct,
            "roles": roles,
            "permissions": effective,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        spec = dict(request.specification or {})
        if "roles" not in spec and "roles" not in current:
            return {**current, **spec}
        direct = [
            str(p)
            for p in spec.get(
                "permissions",
                current.get("directPermissions", current.get("permissions", [])),
            )
        ]
        roles = [str(r) for r in spec.get("roles", current.get("roles", []))]
        effective = self._catalog.effective_permissions(direct, roles)
        return {
            **current,
            **spec,
            "directPermissions": direct,
            "roles": roles,
            "permissions": effective,
        }

    def rolled_out(self, current: Mapping[str, Any]) -> dict[str, Any] | None:
        """Re-expande as `permissions` do usuário quando uma `ipm.role` atribuída muda (0083)."""
        if current.get("lifecycle") != "present":
            return None
        raw_roles = cast(list[Any], current.get("roles") or [])
        roles = [str(r) for r in raw_roles]
        if not roles:
            return None
        raw_direct = cast(list[Any], current.get("directPermissions") or [])
        direct = [str(p) for p in raw_direct]
        effective = self._catalog.effective_permissions(direct, roles)
        if current.get("permissions") == effective:
            return None
        return {**current, "permissions": effective}

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        # Com `lifecycle: absent`, o `desired` não carrega dados pessoais (schema `desired`).
        kept = {
            key: value
            for key, value in current.items()
            if key not in (*PERSONAL_FIELDS, *INTERNAL_DESIRED_FIELDS)
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
        """Permissão fora do módulo `ipm`: o Executor não a concederia (o Receiver recusa antes)."""
        permissions: list[str] = desired.get("permissions", [])
        return any(
            not permission.startswith(PERMISSION_MODULE_PREFIX) for permission in permissions
        )

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
            key: value for key, value in desired.items() if key not in INTERNAL_DESIRED_FIELDS
        }
        model = generated.UserDesiredData.model_validate(
            {**external, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        # Campos gerenciados do usuário: `lifecycle`, `permissions` e `deletionProtection`, este
        # pelo metadado (schemas/ipm/user/desired; decisão 0074). Os dados pessoais e a
        # Organization não são gerenciados: são imutáveis e definidos na criação.
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        return (
            presence == "present"
            and observed is not None
            and sorted(observed.get("permissions") or [])
            == sorted(desired.get("permissions") or [])
            and observed.get("deletionProtection") == self.deletion_protected(desired)
        )
