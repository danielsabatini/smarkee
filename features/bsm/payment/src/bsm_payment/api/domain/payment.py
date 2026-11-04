"""Regras de negócio do método de pagamento (`bsm.payment`), aplicadas na admissão síncrona.

Puro: sem banco, rede ou relógio. O `displayName` único por dono (`ownerAccountId`) entre métodos
de pagamento ativos (`lifecycle = present`) e a cota por dono são declarados aqui (`unique_value`,
`owner_quota`) e verificados na mesma transação da admissão pelo adaptador do SSOT.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bsm_payment.common.contracts import generated


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre métodos de pagamento ativos (`lifecycle = present`)."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""

    scope_field: str
    scope_value: str
    """Campo e valor que delimitam a unicidade (o dono do método de pagamento)."""


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de métodos de pagamento por solicitante, conferida na transação da admissão."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações do mesmo dono."""


def desired_for_create(specification: Mapping[str, Any], requested_by: str) -> dict[str, Any]:
    customer_account_id = str(specification.get("customerAccountId") or requested_by)
    return {
        "lifecycle": "present",
        "customerAccountId": customer_account_id,
        "displayName": specification["displayName"],
        "provider": specification["provider"],
        "methodType": specification["methodType"],
        "providerToken": specification["providerToken"],
        "deletionProtection": True,  # todo recurso apagável nasce protegido (decisão 0043)
        "ownerAccountId": customer_account_id,
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(current)
    if "displayName" in changes:
        updated["displayName"] = changes["displayName"]
    if "deletionProtection" in changes:
        updated["deletionProtection"] = changes["deletionProtection"]
    return updated


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, "lifecycle": "absent"}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    """O `displayName` é único para o mesmo dono entre métodos de pagamento ativos."""
    if desired.get("lifecycle") != "present":
        return None
    owner = str(desired["ownerAccountId"])
    display_name = str(desired["displayName"])
    return UniqueValue(
        field="displayName",
        value=display_name,
        lock_key=f"bsm.payment.display_name:{owner}:{display_name}",
        scope_field="ownerAccountId",
        scope_value=owner,
    )


def owner_quota(desired: Mapping[str, Any], limit: int | None) -> OwnerQuota | None:
    """Cota de métodos de pagamento por solicitante, só no create e só com limite."""
    if limit is None:
        return None
    owner = str(desired["ownerAccountId"])
    return OwnerQuota(
        field="ownerAccountId",
        owner=owner,
        limit=limit,
        lock_key=f"bsm.payment.owner:{owner}",
    )


def deletion_protected(current: Mapping[str, Any]) -> bool:
    return current.get("deletionProtection", True) is not False


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    return generated.PaymentDesiredData.model_validate(
        {**desired, "reconciliation": reconciliation}
    ).model_dump(mode="json", exclude_none=True)
