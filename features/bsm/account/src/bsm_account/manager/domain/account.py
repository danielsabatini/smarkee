"""Regras de negócio da Billing Account, aplicadas pelo Manager.

Puro: sem banco, rede ou relógio. A unicidade de `displayName` por dono (`ownerAccountId`) entre
contas ativas (`lifecycle = present`) é declarada aqui (`unique_value`) e verificada na mesma
unidade atômica do pedido pelo adaptador do SSOT (`docs/SSOT.md` §10.1).
"""

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from bsm_account.common.contracts import generated
from bsm_account.common.contracts.base import ContractModel, fields_of, validate_tolerant
from bsm_account.manager.domain.errors import PermanentMessageError
from bsm_account.manager.domain.policy import Request, UniqueValue

FREE_TIER_DISPLAY_NAME = "Free Tier"
FREE_TIER_CURRENCY = "BRL"


def free_tier_resource_id(owner_account_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bsm.account:free-tier:{owner_account_id}"))


def free_tier_operation_id(owner_account_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"bsm.account:free-tier-operation:{owner_account_id}")
    )


def free_tier_specification(email: str) -> dict[str, Any]:
    return {
        "displayName": FREE_TIER_DISPLAY_NAME,
        "billingCurrency": FREE_TIER_CURRENCY,
        "billingContacts": [email],
    }


def free_tier_request_digest(email: str) -> str:
    content = {"operation": "create", "specification": free_tier_specification(email)}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def free_tier_desired(owner_account_id: str, email: str) -> dict[str, Any]:
    return {
        "lifecycle": "present",
        **free_tier_specification(email),
        "deletionProtection": True,
        "ownerAccountId": owner_account_id,
    }


def free_tier_absent_desired(current: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, "deletionProtection": False, "lifecycle": "absent"}


def free_tier_remove_operation_id(owner_account_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"bsm.account:free-tier-remove-operation:{owner_account_id}")
    )


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


def _contacts(items: list[generated.BillingContact], *, label: str) -> list[str]:
    values = [str(item.root) for item in items]
    if len(set(values)) != len(values):
        raise PermanentMessageError(
            f"{label} inválido nos campos: ['specification.billingContacts']"
        )
    return values


class AccountPolicy:
    """Billing Account: `displayName` único por dono enquanto ativa, `billingCurrency` imutável."""

    def parse(self, operation: str, data: Mapping[str, Any]) -> Request:
        match operation:
            case "create":
                create = _validated(
                    generated.BillingAccountRequestedCreateData, data, label="requested/create"
                )
                return Request(
                    "create",
                    create.operation_id,
                    create.request_digest,
                    specification={
                        "displayName": create.specification.display_name,
                        "billingCurrency": create.specification.billing_currency.value,
                        "billingContacts": _contacts(
                            create.specification.billing_contacts, label="requested/create"
                        ),
                    },
                )
            case "update":
                update = _validated(
                    generated.BillingAccountRequestedUpdateData, data, label="requested/update"
                )
                specification: dict[str, Any] = {}
                if update.specification is not None:
                    if update.specification.display_name is not None:
                        specification["displayName"] = update.specification.display_name
                    if update.specification.billing_contacts is not None:
                        specification["billingContacts"] = _contacts(
                            update.specification.billing_contacts, label="requested/update"
                        )
                    if update.specification.deletion_protection is not None:
                        specification["deletionProtection"] = (
                            update.specification.deletion_protection
                        )
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
                    generated.BillingAccountRequestedDeleteData, data, label="requested/delete"
                )
                return Request(
                    "delete",
                    delete.operation_id,
                    delete.request_digest,
                    resource_version=_parse_resource_version(delete.resource_version),
                )
            case _:
                raise PermanentMessageError(f"operação não suportada para account: {operation}")

    def desired_for_create(self, request: Request, requested_by: str) -> dict[str, Any]:
        assert request.specification is not None  # noqa: S101 (invariante de parse)
        return {
            "lifecycle": "present",
            "displayName": request.specification["displayName"],
            "billingCurrency": request.specification["billingCurrency"],
            "billingContacts": list(request.specification["billingContacts"]),
            "deletionProtection": True,  # todo recurso apagável nasce protegido (decisão 0043)
            "ownerAccountId": requested_by,
        }

    def desired_for_update(self, current: Mapping[str, Any], request: Request) -> dict[str, Any]:
        return {**current, **(request.specification or {})}

    def desired_for_delete(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return {**current, "lifecycle": "absent"}

    def unique_value(self, desired: Mapping[str, Any]) -> UniqueValue | None:
        if desired["lifecycle"] != "present":
            return None
        owner: str = desired["ownerAccountId"]
        display_name: str = desired["displayName"]
        return UniqueValue(
            field="displayName",
            value=display_name,
            owner=owner,
            lock_key=f"bsm.account.display_name:{owner}:{display_name}",
        )

    def invalid(self, desired: Mapping[str, Any]) -> bool:
        """Contatos repetidos não são permitidos."""
        contacts: list[str] = desired.get("billingContacts", [])
        return desired["lifecycle"] == "present" and len(set(contacts)) != len(contacts)

    def deletion_protected(self, current: Mapping[str, Any]) -> bool:
        return current.get("deletionProtection", True) is not False

    def message_data(self, desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
        model = generated.BillingAccountDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        )
        return model.model_dump(mode="json", exclude_none=True)

    def is_converged(
        self, desired: Mapping[str, Any], presence: str, observed: Mapping[str, Any] | None
    ) -> bool:
        # Campos gerenciados da Billing Account: `lifecycle`, `displayName`, `billingCurrency`,
        # `billingContacts` e `deletionProtection` (decisão 0074). `ownerAccountId` não é
        # gerenciado no provedor.
        if desired["lifecycle"] == "absent":
            return presence == "absent"
        return (
            presence == "present"
            and observed is not None
            and observed.get("displayName") == desired["displayName"]
            and observed.get("billingCurrency") == desired["billingCurrency"]
            and observed.get("billingContacts") == desired["billingContacts"]
            and observed.get("deletionProtection") == self.deletion_protected(desired)
        )
