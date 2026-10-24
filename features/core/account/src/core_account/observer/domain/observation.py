"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` da Account."""

from dataclasses import dataclass
from typing import Any, Protocol

from core_account.observer.domain.identity import IdentityUser, ProviderError

_STATE = {
    "USER_STATE_ACTIVE": "active",
    "USER_STATE_INITIAL": "initial",
    "USER_STATE_INACTIVE": "inactive",
    "USER_STATE_LOCKED": "locked",
}


class Users(Protocol):
    """Driver de leitura do usuário (`observer/drivers/user.py`)."""

    async def get_user(self, user_id: str) -> IdentityUser | None: ...


class Authorizations(Protocol):
    """Driver de leitura da autorização (`observer/drivers/authorization.py`)."""

    async def granted_permissions(self, user_id: str) -> set[str]: ...


class Metadata(Protocol):
    """Driver de leitura do metadado do provedor (`observer/drivers/metadata.py`)."""

    async def get_value(self, owner_id: str, key: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    users: Users
    authorizations: Authorizations
    metadata: Metadata


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


def account_state(user: IdentityUser) -> str:
    """`initial` enquanto a senha não foi definida (a ativação não terminou)."""
    mapped = _STATE.get(user.state, "inactive")
    if mapped == "active" and not user.password_set:
        return "initial"
    return mapped


async def observe(drivers: Drivers, user_id: str) -> Observation:
    """Lê o usuário e as permissões. Qualquer falha de leitura é `unknown`, nunca `absent`.

    `platformPermissions` são as permissões que o usuário tem nos projetos da plataforma (decisão
    0025); `platformAccess` é `granted` quando há ao menos uma. Quem compara com o `desired` é o
    Reconciler.
    """
    try:
        user = await drivers.users.get_user(user_id)
        if user is None:
            return Observation("absent", {})
        permissions = await drivers.authorizations.granted_permissions(user_id)
        protection = await drivers.metadata.get_value(user_id, DELETION_PROTECTION_KEY)
    except ProviderError:
        return Observation("unknown", {})
    return Observation(
        "present",
        {
            "emailVerified": user.email_verified,
            "accountState": account_state(user),
            "platformAccess": "granted" if permissions else "revoked",
            "platformPermissions": sorted(permissions),
            **deletion_protection(protection),
        },
    )


DELETION_PROTECTION_KEY = "deletionProtection"
_PROTECTION = {"true": True, "false": False}


def deletion_protection(value: str | None) -> dict[str, bool]:
    """O campo `deletionProtection` do `observed`, a partir do metadado (decisão 0074).

    Metadado ausente ou com outro valor fica fora do `observed`: o Reconciler o vê como divergência
    e o Executor o regrava. Não se inventa um valor que o provedor não tem.
    """
    protected = _PROTECTION.get(value or "")
    return {} if protected is None else {"deletionProtection": protected}


def log_identifiers(resource_id: str) -> dict[str, str]:
    """Identificadores de negócio extras nos logs de cada observação (decisão 0061).

    Gancho que o motor do Observer (template, perfil `loop-engines`) chama. A Account não é uma
    Organization: não há identificador extra.
    """
    return {}
