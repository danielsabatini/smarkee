"""Regras de negócio da Organization, aplicadas pelo Manager (decisão 0010).

Puro: sem banco, rede ou relógio. O nome único, os nomes reservados e a cota por dono são declarados
aqui (`unique_value`, `invalid`, `owner_quota`) e verificados na mesma unidade atômica do pedido
pelo adaptador do SSOT (`docs/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_organization_manager.contracts import generated
from ipm_organization_manager.contracts.base import ContractModel, validate_tolerant
from ipm_organization_manager.domain.errors import PermanentMessageError
from ipm_organization_manager.domain.policy import OwnerQuota, Request, UniqueValue

# Nomes que nenhuma Organization de cliente pode usar (decisão 0010): organizações de sistema
# do Zitadel e termos que se confundiriam com a plataforma. Lista da plataforma, em código por
# enquanto; vira configuração quando houver necessidade.
RESERVED_ORGANIZATION_NAMES = frozenset(
    {"core", "smarkee", "register", "platform", "system", "admin", "zitadel"}
)


def _validated[M: ContractModel](model: type[M], data: Mapping[str, Any], *, label: str) -> M:
    try:
        return validate_tolerant(model, data)
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        raise PermanentMessageError(f"{label} inválido nos campos: {fields}") from None


def _parse_resource_version(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise PermanentMessageError("resourceVersion não numérico") from None


class OrganizationPolicy:
    """Organization: nome único e não reservado, dono imutável e cota por dono (decisão 0010)."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.OrganizationRequestedCreateData, data, label="requested/create"
                )
                return Request(
                    "create",
                    create.operation_id,
                    create.request_digest,
                    specification={
                        "name": create.specification.name,
                        "platformAccess": create.specification.platform_access.value,
                    },
                    owner_quota_limit=create.owner_quota_limit,
                )
            case "update":
                update = _validated(
                    generated.OrganizationRequestedUpdateData, data, label="requested/update"
                )
                specification: dict[str, Any] = {}
                if update.specification is not None:
                    if update.specification.name is not None:
                        specification["name"] = update.specification.name
                    if update.specification.platform_access is not None:
                        specification["platformAccess"] = update.specification.platform_access.value
                return Request(
                    "update",
                    update.operation_id,
                    update.request_digest,
                    resource_version=_parse_resource_version(update.resource_version),
                    specification=specification,
                    reconciliation=update.reconciliation.value if update.reconciliation else None,
                )
            case "delete":
                delete = _validated(
                    generated.OrganizationRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(
                    f"operação não suportada para organization: {operation}"
                )

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        return {
            "lifecycle": "present",
            "name": request.specification["name"],
            "platformAccess": request.specification["platformAccess"],
            "ownerUserId": requested_by,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        return {**current, **(request.specification or {})}

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return {**current, "lifecycle": "absent"}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        if desired["lifecycle"] != "present":
            return None
        name: str = desired["name"]
        return UniqueValue(field="name", value=name, lock_key=f"ipm.organization.name:{name}")

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        """Nome reservado: nenhuma Organization de cliente pode usá-lo."""
        return desired["lifecycle"] == "present" and desired["name"] in RESERVED_ORGANIZATION_NAMES

    def owner_quota(self, request: Request, desired: Mapping[str, Any]) -> OwnerQuota | None:
        """Cota de Organizations por dono, só no create e só quando o Receiver definiu um limite.

        O Receiver não define limite para o operador (decisão 0010).
        """
        if request.operation != "create" or request.owner_quota_limit is None:
            return None
        owner: str = desired["ownerUserId"]
        return OwnerQuota(
            field="ownerUserId",
            owner=owner,
            limit=request.owner_quota_limit,
            lock_key=f"ipm.organization.owner:{owner}",
        )

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.OrganizationDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        # Campos gerenciados da Organization: `lifecycle`, `name` e `platformAccess`
        # (schemas/ipm/organization/desired). `ownerUserId` não é gerenciado: não existe no Zitadel.
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        return (
            presence == "present"
            and observed is not None
            and observed.get("name") == desired["name"]
            and observed.get("platformAccess") == desired["platformAccess"]
        )
