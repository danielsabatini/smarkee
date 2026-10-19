"""Observação de uma ligação de `sum.service`: do Zitadel para o contrato `observed` (decisão 0033).

Puro: recebe o leitor (uma porta) e devolve a observação. Qualquer falha de leitura é `unknown`,
nunca `absent`: só a confirmação de que o usuário não existe é ausência.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sum_service.observer.domain.authorization import Authorization, ProviderError


class Reader(Protocol):
    async def user_exists(self, user_id: str) -> bool: ...

    async def authorizations(self, user_id: str) -> list[Authorization]: ...


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(
    reader: Reader,
    user_id: str,
    service: str,
    catalog: Mapping[str, tuple[str, ...]],
) -> Observation:
    """Lê as roles do usuário que pertencem ao serviço (as do catálogo do Manager)."""
    service_roles = set(catalog.get(service, ()))
    try:
        if not await reader.user_exists(user_id):
            return Observation("absent", {"serviceRoles": []})
        authorizations = await reader.authorizations(user_id)
    except ProviderError:
        return Observation("unknown", {})
    held = sorted(
        {role for authorization in authorizations for role in authorization.roles} & service_roles
    )
    return Observation("present", {"serviceRoles": held})
