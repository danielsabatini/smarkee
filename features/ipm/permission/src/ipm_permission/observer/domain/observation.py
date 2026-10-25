"""Observação da Permission: da leitura da role de projeto no Zitadel para `observed`.

Puro: recebe os drivers de leitura (portas) e devolve a observação da Permission. Qualquer falha
de leitura é `unknown`, nunca `absent`: só a confirmação de que a role não existe no projeto
`roles-<módulo>` é ausência.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from ipm_permission.observer.domain.identity import IdentityProjectRole, ProviderError


class ProjectRoles(Protocol):
    """Driver de leitura da role de projeto (`observer/drivers/project_role.py`)."""

    async def get(self, permission_name: str) -> IdentityProjectRole | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    project_roles: ProjectRoles


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown` (`schemas/common/envelope`)."""

    observed: dict[str, Any]
    """Campos de `schemas/ipm/permission/observed` (vazio em `absent` e `unknown`)."""


async def observe(drivers: Drivers, permission_name: str | None) -> Observation:
    """Observa a Permission pelo nome (`<módulo>.<tipo>.<ação>`) no projeto `roles-<módulo>`."""
    if not permission_name:
        return Observation(presence="unknown", observed={})
    try:
        role = await drivers.project_roles.get(permission_name)
    except ProviderError:
        return Observation(presence="unknown", observed={})
    if role is None:
        return Observation(presence="absent", observed={})
    return Observation(
        presence="present",
        observed={
            "name": role.key,
            "description": role.display_name,
            "group": role.group,
        },
    )
