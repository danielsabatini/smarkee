"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` do usuário."""

from dataclasses import dataclass
from typing import Any, Protocol, cast

from ipm_user.observer.domain.identity import IdentityUser, ProviderError

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
    """Driver de leitura da autorização em `roles-ipm` (`observer/drivers/authorization.py`)."""

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


def user_state(user: IdentityUser) -> str:
    """`initial` enquanto a senha não foi definida (a ativação não terminou)."""
    mapped = _STATE.get(user.state, "inactive")
    if mapped == "active" and not user.password_set:
        return "initial"
    return mapped


async def observe(drivers: Drivers, user_id: str) -> Observation:
    """Lê o usuário e as permissões. Qualquer falha de leitura é `unknown`, nunca `absent`.

    `permissions` são as permissões que o usuário tem em `roles-ipm`, pelo Project Grant da
    Organization (decisão 0077). Quem compara com o `desired` é o Reconciler.
    """
    try:
        user = await drivers.users.get_user(user_id)
        if user is None:
            return Observation("absent", {})
        permissions = await drivers.authorizations.granted_permissions(user_id)
        protection = await drivers.metadata.get_value(user_id, DELETION_PROTECTION_KEY)
        groups_raw = await drivers.metadata.get_value(user_id, GROUPS_METADATA_KEY)
    except ProviderError:
        return Observation("unknown", {})
    return Observation(
        "present",
        {
            "emailVerified": user.email_verified,
            "userState": user_state(user),
            "permissions": sorted(permissions),
            **deletion_protection(protection),
            **groups_metadata(groups_raw),
        },
    )


DELETION_PROTECTION_KEY = "deletionProtection"
GROUPS_METADATA_KEY = "groups"
_PROTECTION = {"true": True, "false": False}


def groups_metadata(value: str | None) -> dict[str, list[str]]:
    """O campo `groups` do `observed`, lido do metadado (decisão 0088)."""
    if not value:
        return {}
    import json

    try:
        doc: object = json.loads(value)
        if isinstance(doc, list):
            return {"groups": sorted({str(g) for g in cast("list[object]", doc)})}
    except (ValueError, TypeError):
        return {}
    return {}


def deletion_protection(value: str | None) -> dict[str, bool]:
    """O campo `deletionProtection` do `observed`, a partir do metadado (decisão 0074).

    Metadado ausente ou com outro valor fica fora do `observed`: o Reconciler o vê como divergência
    e o Executor o regrava. Não se inventa um valor que o provedor não tem.
    """
    protected = _PROTECTION.get(value or "")
    return {} if protected is None else {"deletionProtection": protected}


def log_identifiers(resource_id: str) -> dict[str, str]:
    """Identificadores de negócio extras nos logs de cada observação (decisão 0061).

    Gancho que o motor do Observer (template, perfil `loop-engines`) chama. A observação lê só o
    `resourceId` do usuário: a Organization dele não entra no log do Observer.
    """
    return {}
