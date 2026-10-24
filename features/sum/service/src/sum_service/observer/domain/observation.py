"""Observação de uma ligação de `sum.service`: do Zitadel para o contrato `observed` (decisão 0033).

Puro: recebe os drivers de leitura (portas) e devolve a observação. Qualquer falha de
leitura é `unknown`, nunca `absent`: só a confirmação de que o usuário não existe é ausência.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from sum_service.observer.domain.authorization import Authorization, ProviderError


class Users(Protocol):
    """Driver de leitura do usuário (`observer/drivers/user.py`)."""

    async def user_exists(self, user_id: str) -> bool: ...


class Authorizations(Protocol):
    """Driver de leitura da autorização (`observer/drivers/authorization.py`)."""

    async def authorizations(self, user_id: str) -> list[Authorization]: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    users: Users
    authorizations: Authorizations


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(
    drivers: Drivers,
    user_id: str,
    managed_permissions: Iterable[str],
) -> Observation:
    """Lê as permissões do usuário que a ligação controla (`managedPermissions` do `desired`,
    decisão 0079).

    O Observer não tem catálogo próprio: as permissões vêm do `desired` que o Manager publicou, a
    mesma fonte do Executor e do Reconciler.
    """
    service_permissions = set(managed_permissions)
    try:
        if not await drivers.users.user_exists(user_id):
            return Observation("absent", {"servicePermissions": []})
        authorizations = await drivers.authorizations.authorizations(user_id)
    except ProviderError:
        return Observation("unknown", {})
    held = sorted(
        {permission for authorization in authorizations for permission in authorization.permissions}
        & service_permissions
    )
    return Observation("present", {"servicePermissions": held})
