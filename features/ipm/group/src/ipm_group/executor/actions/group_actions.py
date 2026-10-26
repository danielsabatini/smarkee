"""Execução das operações do Grupo no estado do Grupo, no banco `platform` (`LOOP.md` §46).

Compõe os drivers de `executor/drivers/` e não chama o provedor direto. Cada operação é idempotente
e usa o `resourceId` como identificador do Grupo. `name` e `organizationId` são imutáveis após a
criação.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ipm_group.executor.domain.errors import ActionFailedError
from ipm_group.executor.domain.identity import StoredGroup


class Groups(Protocol):
    """Driver do Grupo (`executor/drivers/group.py`)."""

    async def get_group(self, group_id: str) -> StoredGroup | None: ...

    async def save_group(self, group_id: str, group: StoredGroup) -> None: ...

    async def delete_group(self, group_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações do Grupo usam."""

    groups: Groups


async def execute(
    operation: str,
    group_id: str,
    desired: Mapping[str, Any],
    drivers: Drivers,
) -> None:
    writer = drivers.groups
    match operation:
        case "create":
            await _create(group_id, desired, writer)
        case "update":
            await _update(group_id, desired, writer)
        case "delete":
            await writer.delete_group(group_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _group_of(desired: Mapping[str, Any]) -> StoredGroup:
    org_id = str(desired.get("organizationId", ""))
    if not org_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without organizationId"
        )
    name = str(desired.get("name", ""))
    if not name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without name")
    description = str(desired.get("description", ""))
    if not description:
        raise ActionFailedError("Rejected", retryable=False, message="desired without description")
    raw_roles = desired.get("roles")
    if not isinstance(raw_roles, list):
        roles: list[str] = []
    else:
        roles = sorted({str(item) for item in raw_roles})  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    protected = desired.get("deletionProtection", False) is True
    return StoredGroup(
        organization_id=org_id,
        name=name,
        description=description,
        roles=roles,
        deletion_protection=protected,
    )


async def _create(group_id: str, desired: Mapping[str, Any], writer: Groups) -> None:
    target = _group_of(desired)
    existing = await writer.get_group(group_id)
    if existing is not None and (
        existing.name != target.name or existing.organization_id != target.organization_id
    ):
        raise ActionFailedError(
            "Rejected", retryable=False, message="group name and organizationId cannot be changed"
        )
    await writer.save_group(group_id, target)


async def _update(group_id: str, desired: Mapping[str, Any], writer: Groups) -> None:
    target = _group_of(desired)
    existing = await writer.get_group(group_id)
    if existing is None:
        raise ActionFailedError("Rejected", retryable=False, message="group does not exist")
    if existing.name != target.name or existing.organization_id != target.organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="group name and organizationId cannot be changed"
        )
    await writer.save_group(group_id, target)
