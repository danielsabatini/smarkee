"""Observação do estado real da ligação de serviço no Zitadel (decisões 0033, 0079 e 0096).

Lê se o usuário existe e as permissões dele nos projetos configurados, limitadas às que a ligação
controla (`managedPermissions` do `desired`). Falha de leitura é `unknown`, nunca `absent`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sum_service.controller.drivers.authorization import AuthorizationDriver
from sum_service.controller.drivers.identity import ProviderError
from sum_service.controller.drivers.user import UserDriver


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


async def observe_service(
    user_id: str,
    managed_permissions: Iterable[str],
    *,
    users: UserDriver,
    authorizations: AuthorizationDriver,
) -> ObservationResult:
    """Lê o usuário e as permissões gerenciadas. Qualquer falha de leitura é `unknown`."""
    managed = set(managed_permissions)
    try:
        if not await users.exists(user_id):
            return ObservationResult("absent", {"servicePermissions": []})
        grants = await authorizations.grants(user_id)
    except ProviderError:
        return ObservationResult("unknown", {})
    held = sorted({permission for grant in grants for permission in grant.permissions} & managed)
    return ObservationResult("present", {"servicePermissions": held})
