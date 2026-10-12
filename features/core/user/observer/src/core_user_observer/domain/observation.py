"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` do User."""

from dataclasses import dataclass
from typing import Any, Protocol

from core_user_observer.domain.identity import ProviderError, ZitadelUser

_STATE = {
    "USER_STATE_ACTIVE": "active",
    "USER_STATE_INITIAL": "initial",
    "USER_STATE_INACTIVE": "inactive",
    "USER_STATE_LOCKED": "locked",
}


class ExpectedRoles(Protocol):
    """Roles que o usuário deve ter para `platformAccess = granted` (vêm da configuração)."""

    @property
    def expected_roles(self) -> tuple[str, ...]: ...


class Reader(Protocol):
    """Leitura do provedor de identidade (implementada por `ZitadelReader`)."""

    async def get_user(self, user_id: str) -> ZitadelUser | None: ...

    async def granted_roles(self, user_id: str) -> set[str]: ...


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


def user_state(user: ZitadelUser) -> str:
    """`initial` enquanto a senha não foi definida (a ativação não terminou)."""
    mapped = _STATE.get(user.state, "inactive")
    if mapped == "active" and not user.password_set:
        return "initial"
    return mapped


async def observe(reader: Reader, settings: ExpectedRoles, user_id: str) -> Observation:
    """Lê o usuário e as roles. Qualquer falha de leitura é `unknown`, nunca `absent`."""
    try:
        user = await reader.get_user(user_id)
        if user is None:
            return Observation("absent", {})
        roles = await reader.granted_roles(user_id)
    except ProviderError:
        return Observation("unknown", {})
    granted = set(settings.expected_roles) <= roles
    return Observation(
        "present",
        {
            "emailVerified": user.email_verified,
            "userState": user_state(user),
            "platformAccess": "granted" if granted else "revoked",
        },
    )
