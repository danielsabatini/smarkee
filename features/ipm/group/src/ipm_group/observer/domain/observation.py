"""Resultado de uma observação: mapeia o estado persistido para `observed` de `ipm.group`."""

from dataclasses import dataclass
from typing import Any, Protocol

from ipm_group.observer.domain.identity import ProviderError, StoredGroup


class Groups(Protocol):
    """Driver de leitura do Grupo (`observer/drivers/group.py`)."""

    async def get_group(self, group_id: str) -> StoredGroup | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    groups: Groups


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(drivers: Drivers, group_id: str) -> Observation:
    """Lê o Grupo. Qualquer falha de leitura é `unknown`, nunca `absent`."""
    try:
        group = await drivers.groups.get_group(group_id)
    except ProviderError:
        return Observation("unknown", {})
    if group is None:
        return Observation("absent", {})
    if not group.name or not group.description:
        return Observation("unknown", {})
    data: dict[str, Any] = {
        "name": group.name,
        "description": group.description,
        "roles": sorted(set(group.roles)),
    }
    if group.deletion_protection is not None:
        data["deletionProtection"] = group.deletion_protection
    return Observation("present", data)


def log_identifiers(resource_id: str) -> dict[str, str]:
    """Identificadores de negócio extras nos logs de cada observação (decisão 0061)."""
    _ = resource_id
    return {}
