"""Observação do estado real do usuário da Organization no Zitadel (decisões 0077 e 0096).

Lê o usuário, as permissões (autorizações em `roles-ipm`), a proteção contra exclusão e os grupos
(metadados). Falha de leitura é `unknown`, nunca `absent`.
"""

import json
from dataclasses import dataclass
from typing import Any, cast

from ipm_user.controller.drivers.authorization import AuthorizationDriver
from ipm_user.controller.drivers.identity import ProviderError
from ipm_user.controller.drivers.metadata import MetadataDriver
from ipm_user.controller.drivers.user import IdentityUser, UserDriver

_STATE = {
    "USER_STATE_ACTIVE": "active",
    "USER_STATE_INITIAL": "initial",
    "USER_STATE_INACTIVE": "inactive",
    "USER_STATE_LOCKED": "locked",
}
DELETION_PROTECTION_KEY = "deletionProtection"
GROUPS_METADATA_KEY = "groups"
_PROTECTION = {"true": True, "false": False}


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


def user_state(user: IdentityUser) -> str:
    """`initial` enquanto a senha não foi definida (a ativação não terminou)."""
    mapped = _STATE.get(user.state, "inactive")
    if mapped == "active" and not user.password_set:
        return "initial"
    return mapped


async def observe_user(
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
        permissions = await authorizations.granted_permissions(user_id)
        protection = await metadata.get_value(user_id, DELETION_PROTECTION_KEY)
        groups_raw = await metadata.get_value(user_id, GROUPS_METADATA_KEY)
    except ProviderError:
        return ObservationResult("unknown", {})
    return ObservationResult(
        "present",
        {
            "emailVerified": user.email_verified,
            "userState": user_state(user),
            "permissions": sorted(permissions),
            **deletion_protection(protection),
            **groups_metadata(groups_raw),
        },
    )


def groups_metadata(value: str | None) -> dict[str, list[str]]:
    """O campo `groups` do `observed`, lido do metadado (decisão 0088)."""
    if not value:
        return {}
    try:
        doc: object = json.loads(value)
    except ValueError:
        return {}
    if isinstance(doc, list):
        return {"groups": sorted({str(g) for g in cast("list[object]", doc)})}
    return {}


def deletion_protection(value: str | None) -> dict[str, bool]:
    """O campo `deletionProtection` do `observed`, a partir do metadado (decisão 0074).

    Metadado ausente ou com outro valor fica fora do `observed`: a decisão o vê como divergência
    e a ação o regrava. Não se inventa um valor que o provedor não tem.
    """
    protected = _PROTECTION.get(value or "")
    return {} if protected is None else {"deletionProtection": protected}
