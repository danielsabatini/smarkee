"""Regras de negócio da Organization, aplicadas na admissão (decisões 0010 e 0098).

Puro: sem banco, rede ou relógio. O nome único e a cota de Organizations por dono são declarados
aqui (`unique_value`, `owner_quota`) e verificados na mesma transação da admissão pelo adaptador do
SSOT (`docs/data/SSOT.md` §10.1).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ipm_organization.common.contracts import generated

# Nomes que nenhuma Organization de cliente pode usar (decisão 0010): organizações de sistema
# do Zitadel e termos que se confundiriam com a plataforma. Lista da plataforma, em código por
# enquanto; vira configuração quando houver necessidade.
RESERVED_ORGANIZATION_NAMES = frozenset(
    {"core", "smarkee", "register", "operator", "platform", "system", "admin", "zitadel"}
)


@dataclass(frozen=True, slots=True)
class UniqueValue:
    """Valor que não pode se repetir entre as Organizations."""

    field: str
    value: str
    lock_key: str
    """Chave que serializa as transações que disputam o mesmo valor."""


@dataclass(frozen=True, slots=True)
class OwnerQuota:
    """Cota de Organizations por dono, conferida na transação da admissão."""

    field: str
    owner: str
    limit: int
    lock_key: str
    """Chave que serializa as transações do mesmo dono."""


def desired_for_create(
    specification: Mapping[str, Any],
    requested_by: str,
    *,
    user_access: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    billing_account_id = specification.get("billingAccountId")
    return {
        "lifecycle": "present",
        "name": specification["name"],
        "platformAccess": specification["platformAccess"],
        "deletionProtection": True,  # todo recurso apagável nasce protegido (decisão 0043)
        **({"userAccess": dict(user_access)} if user_access is not None else {}),
        **({"billingAccountId": billing_account_id} if billing_account_id is not None else {}),
        "ownerAccountId": requested_by,
    }


def desired_for_update(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, **changes}


def desired_for_delete(current: Mapping[str, Any]) -> dict[str, Any]:
    return {**current, "lifecycle": "absent"}


def unique_value(desired: Mapping[str, Any]) -> UniqueValue | None:
    if desired["lifecycle"] != "present":
        return None
    name: str = desired["name"]
    return UniqueValue(field="name", value=name, lock_key=f"ipm.organization.name:{name}")


def is_reserved_name(name: str) -> bool:
    """Nome reservado: nenhuma Organization de cliente pode usá-lo."""
    return name.lower() in RESERVED_ORGANIZATION_NAMES


def owner_quota(desired: Mapping[str, Any], limit: int | None) -> OwnerQuota | None:
    """Cota de Organizations por dono, só no create e só com limite.

    O operador não tem cota (decisão 0010).
    """
    if limit is None:
        return None
    owner: str = desired["ownerAccountId"]
    return OwnerQuota(
        field="ownerAccountId",
        owner=owner,
        limit=limit,
        lock_key=f"ipm.organization.owner:{owner}",
    )


def deletion_protected(current: Mapping[str, Any]) -> bool:
    return current.get("deletionProtection", True) is not False


def message_data(desired: Mapping[str, Any], reconciliation: str) -> dict[str, Any]:
    model = generated.OrganizationDesiredData.model_validate(
        {**desired, "reconciliation": reconciliation}
    )
    return model.model_dump(mode="json", exclude_none=True)
