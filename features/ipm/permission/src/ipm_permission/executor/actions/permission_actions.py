"""Ações do Executor da Permission (`create`, `update`, `delete`) sobre `roles-<módulo>`.

Cada ação é idempotente: criar uma role que já existe atualiza sua descrição e grupo; remover uma
role já ausente conclui com sucesso.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ipm_permission.executor.domain.errors import ActionFailedError


class ProjectRoles(Protocol):
    """Driver de escrita das roles de projeto (`executor/drivers/project_role.py`)."""

    async def add_or_update_role(
        self, module: str, role_key: str, *, display_name: str, group: str
    ) -> None: ...

    async def update_role(
        self, module: str, role_key: str, *, display_name: str, group: str
    ) -> None: ...

    async def remove_role(self, module: str, role_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as ações usam."""

    project_roles: ProjectRoles


async def execute(
    operation: str, _resource_id: str, desired_data: Mapping[str, Any], drivers: Drivers
) -> None:
    name = str(desired_data.get("name", ""))
    description = str(desired_data.get("description", ""))
    parts = name.split(".")
    if len(parts) != 3 or not all(parts) or not description:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired data is incomplete or invalid"
        )
    module = parts[0]
    target = "operator" if parts[2] == "admin" else module
    match operation:
        case "create":
            await drivers.project_roles.add_or_update_role(
                target, name, display_name=description, group=module
            )
        case "update":
            await drivers.project_roles.update_role(
                target, name, display_name=description, group=module
            )
        case "delete":
            await drivers.project_roles.remove_role(target, name)
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="operation not allowed")
