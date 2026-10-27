"""Observação estruturada da role de projeto da Permission no Zitadel (decisões 0083 e 0096).

Qualquer falha de leitura é `unknown`, nunca `absent`: só a confirmação de que a role não existe
no projeto é ausência.
"""

from dataclasses import dataclass
from typing import Any

from ipm_permission.controller.drivers.identity import ProviderError
from ipm_permission.controller.drivers.project_role import ProjectRoleDriver


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


async def observe_permission(
    permission_name: str, *, roles: ProjectRoleDriver
) -> ObservationResult:
    if not permission_name:
        return ObservationResult("unknown", {})
    try:
        role = await roles.get(permission_name)
    except ProviderError:
        return ObservationResult("unknown", {})
    if role is None:
        return ObservationResult("absent", {})
    return ObservationResult(
        "present",
        {"name": role.key, "description": role.display_name, "group": role.group},
    )
