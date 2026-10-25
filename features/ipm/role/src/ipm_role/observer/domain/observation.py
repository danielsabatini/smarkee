"""Resultado de uma observação: mapeia o estado persistido para `observed` de `ipm.role`."""

from dataclasses import dataclass
from typing import Any, Protocol

from ipm_role.observer.domain.identity import ProviderError, StoredRole


class Roles(Protocol):
    """Driver de leitura da Role (`observer/drivers/role.py`)."""

    async def get_role(self, role_id: str) -> StoredRole | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    roles: Roles


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(drivers: Drivers, role_id: str) -> Observation:
    """Lê a Role. Qualquer falha de leitura é `unknown`, nunca `absent`."""
    try:
        role = await drivers.roles.get_role(role_id)
    except ProviderError:
        return Observation("unknown", {})
    if role is None:
        return Observation("absent", {})
    if not role.name or not role.description or not role.permissions:
        return Observation("unknown", {})
    data: dict[str, Any] = {
        "name": role.name,
        "description": role.description,
        "permissions": sorted(set(role.permissions)),
    }
    if role.deletion_protection is not None:
        data["deletionProtection"] = role.deletion_protection
    return Observation("present", data)


def log_identifiers(resource_id: str) -> dict[str, str]:
    """Identificadores de negócio extras nos logs de cada observação (decisão 0061)."""
    _ = resource_id
    return {}
