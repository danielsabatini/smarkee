"""Execução das operações da Role no estado da Role, no banco `platform` (`LOOP.md` §46).

Compõe os drivers de `executor/drivers/` e não chama o provedor direto. Cada operação é idempotente
e usa o `resourceId` como identificador da Role. `name` e `organizationId` são imutáveis após a
criação.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ipm_role.executor.domain.errors import ActionFailedError
from ipm_role.executor.domain.identity import StoredRole


class Roles(Protocol):
    """Driver da Role (`executor/drivers/role.py`)."""

    async def get_role(self, role_id: str) -> StoredRole | None: ...

    async def save_role(self, role_id: str, role: StoredRole) -> None: ...

    async def delete_role(self, role_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações da Role usam."""

    roles: Roles


async def execute(
    operation: str,
    role_id: str,
    desired: Mapping[str, Any],
    drivers: Drivers,
) -> None:
    writer = drivers.roles
    match operation:
        case "create":
            await _create(role_id, desired, writer)
        case "update":
            await _update(role_id, desired, writer)
        case "delete":
            await writer.delete_role(role_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _role_of(desired: Mapping[str, Any]) -> StoredRole:
    name = str(desired.get("name", ""))
    if not name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without name")
    description = str(desired.get("description", ""))
    if not description:
        raise ActionFailedError("Rejected", retryable=False, message="desired without description")
    raw_permissions = desired.get("permissions")
    if not isinstance(raw_permissions, list) or not raw_permissions:
        raise ActionFailedError("Rejected", retryable=False, message="desired without permissions")
    permissions = sorted({str(item) for item in raw_permissions})  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    protected = desired.get("deletionProtection", True) is not False
    return StoredRole(
        organization_id=str(desired.get("organizationId") or "core"),
        name=name,
        description=description,
        permissions=permissions,
        deletion_protection=protected,
    )


async def _create(role_id: str, desired: Mapping[str, Any], writer: Roles) -> None:
    target = _role_of(desired)
    existing = await writer.get_role(role_id)
    if existing is not None and (
        existing.name != target.name or existing.organization_id != target.organization_id
    ):
        raise ActionFailedError(
            "Rejected", retryable=False, message="role name and organization cannot be changed"
        )
    await writer.save_role(role_id, target)


async def _update(role_id: str, desired: Mapping[str, Any], writer: Roles) -> None:
    target = _role_of(desired)
    existing = await writer.get_role(role_id)
    if existing is None:
        raise ActionFailedError("Rejected", retryable=False, message="role does not exist")
    if existing.name != target.name or existing.organization_id != target.organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="role name and organization cannot be changed"
        )
    await writer.save_role(role_id, target)
