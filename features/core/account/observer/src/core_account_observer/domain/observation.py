"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` da Account."""

from dataclasses import dataclass
from typing import Any, Protocol

from core_account_observer.domain.identity import ProviderError, ZitadelUser

_STATE = {
    "USER_STATE_ACTIVE": "active",
    "USER_STATE_INITIAL": "initial",
    "USER_STATE_INACTIVE": "inactive",
    "USER_STATE_LOCKED": "locked",
}


class Reader(Protocol):
    """Leitura do provedor de identidade (implementada por `ZitadelReader`)."""

    async def get_user(self, user_id: str) -> ZitadelUser | None: ...

    async def granted_roles(self, user_id: str) -> set[str]: ...


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


def account_state(user: ZitadelUser) -> str:
    """`initial` enquanto a senha não foi definida (a ativação não terminou)."""
    mapped = _STATE.get(user.state, "inactive")
    if mapped == "active" and not user.password_set:
        return "initial"
    return mapped


async def observe(reader: Reader, user_id: str) -> Observation:
    """Lê o usuário e as roles. Qualquer falha de leitura é `unknown`, nunca `absent`.

    `platformRoles` são as roles que o usuário tem no projeto da plataforma (decisão 0025);
    `platformAccess` é `granted` quando há ao menos uma. Quem compara com o `desired` é o
    Reconciler.
    """
    try:
        user = await reader.get_user(user_id)
        if user is None:
            return Observation("absent", {})
        roles = await reader.granted_roles(user_id)
    except ProviderError:
        return Observation("unknown", {})
    return Observation(
        "present",
        {
            "emailVerified": user.email_verified,
            "accountState": account_state(user),
            "platformAccess": "granted" if roles else "revoked",
            "platformRoles": sorted(roles),
        },
    )
