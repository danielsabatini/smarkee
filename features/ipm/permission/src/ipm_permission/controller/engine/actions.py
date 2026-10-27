"""Execução idempotente das operações da Permission no Zitadel (decisões 0083 e 0096).

Criar uma role que já existe atualiza descrição e grupo; remover uma role já ausente conclui.
"""

from collections.abc import Mapping
from typing import Any

from ipm_permission.controller.domain.decision import module_of
from ipm_permission.controller.drivers.project_role import ProjectRoleDriver


class ActionFailedError(Exception):
    def __init__(self, reason: str, *, retryable: bool = False, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message


async def execute(
    operation: str,
    desired: Mapping[str, Any],
    *,
    roles: ProjectRoleDriver,
) -> None:
    name = str(desired.get("name", ""))
    description = str(desired.get("description", ""))
    parts = name.split(".")
    if len(parts) != 3 or not all(parts) or not description:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired data is incomplete or invalid"
        )
    group = module_of(name)
    match operation:
        case "create":
            await roles.add_or_update_role(name, display_name=description, group=group)
        case "update":
            await roles.update_role(name, display_name=description, group=group)
        case "delete":
            await roles.remove_role(name)
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")
