"""Observação do estado real da Account no Zitadel (decisões 0014 e 0096).

Lê o usuário, as permissões (autorizações nos projetos da plataforma) e a proteção contra exclusão
(metadado). Falha de leitura é `unknown`, nunca `absent`. `platformPermissions` são as permissões do
usuário nos projetos da plataforma (decisão 0025); `platformAccess` é `granted` quando há ao menos
uma.
"""

from dataclasses import dataclass
from typing import Any

from core_account.controller.drivers.authorization import AuthorizationDriver
from core_account.controller.drivers.identity import ProviderError
from core_account.controller.drivers.metadata import MetadataDriver
from core_account.controller.drivers.user import IdentityUser, UserDriver

_STATE = {
    "USER_STATE_ACTIVE": "active",
    "USER_STATE_INITIAL": "initial",
    "USER_STATE_INACTIVE": "inactive",
    "USER_STATE_LOCKED": "locked",
}
DELETION_PROTECTION_KEY = "deletionProtection"
_PROTECTION = {"true": True, "false": False}


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


def account_state(user: IdentityUser) -> str:
    """`initial` enquanto a senha não foi definida (a ativação não terminou)."""
    mapped = _STATE.get(user.state, "inactive")
    if mapped == "active" and not user.password_set:
        return "initial"
    return mapped


async def observe_account(
    user_id: str,
    *,
    users: UserDriver,
    authorizations: AuthorizationDriver,
    metadata: MetadataDriver,
) -> ObservationResult:
    """Lê o usuário e as permissões. Qualquer falha de leitura é `unknown`, nunca `absent`."""
    try:
        user = await users.get_user(user_id)
        if user is None:
            return ObservationResult("absent", {})
        grants = await authorizations.grants(user_id)
        protection = await metadata.get_value(user_id, DELETION_PROTECTION_KEY)
    except ProviderError:
        return ObservationResult("unknown", {})
    permissions = sorted({permission for grant in grants for permission in grant.permissions})
    return ObservationResult(
        "present",
        {
            "emailVerified": user.email_verified,
            "accountState": account_state(user),
            "platformAccess": "granted" if permissions else "revoked",
            "platformPermissions": permissions,
            **deletion_protection(protection),
        },
    )


def deletion_protection(value: str | None) -> dict[str, bool]:
    """O campo `deletionProtection` do `observed`, a partir do metadado (decisão 0074).

    Metadado ausente ou com outro valor fica fora do `observed`: a decisão o vê como divergência e a
    ação o regrava. Não se inventa um valor que o provedor não tem.
    """
    protected = _PROTECTION.get(value or "")
    return {} if protected is None else {"deletionProtection": protected}
