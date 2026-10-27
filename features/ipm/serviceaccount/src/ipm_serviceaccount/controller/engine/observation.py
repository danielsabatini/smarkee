"""Observação estruturada do estado real da service account no Zitadel (decisão 0094).

O Zitadel não devolve a chave pública que recebeu. A ação guarda no metadado `keys` o mapa
`fingerprint -> keyId`; aqui ele é cruzado com o `ListKeys` para dar a cada chave o `status`:
`active` (listada) ou `expired` (no mapa, mas já fora da lista do provedor).
"""

import json
from dataclasses import dataclass
from typing import Any, cast

from ipm_serviceaccount.controller.drivers.authorization import AuthorizationDriver
from ipm_serviceaccount.controller.drivers.identity import ProviderError
from ipm_serviceaccount.controller.drivers.metadata import MetadataDriver
from ipm_serviceaccount.controller.drivers.serviceaccount import (
    IdentityKey,
    ServiceAccountDriver,
)

_STATE = {
    "USER_STATE_ACTIVE": "active",
    "USER_STATE_INACTIVE": "inactive",
    "USER_STATE_LOCKED": "locked",
}
_TOKEN_TYPE = {
    "ACCESS_TOKEN_TYPE_JWT": "jwt",
    "ACCESS_TOKEN_TYPE_BEARER": "bearer",
}
DELETION_PROTECTION_KEY = "deletionProtection"
DESCRIPTION_KEY = "description"
KEYS_KEY = "keys"
_PROTECTION = {"true": True, "false": False}


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


async def observe_serviceaccount(
    user_id: str,
    *,
    machines: ServiceAccountDriver,
    authorizations: AuthorizationDriver,
    metadata: MetadataDriver,
) -> ObservationResult:
    """Lê a máquina, as permissões e as chaves. Falha de leitura é `unknown`, nunca `absent`."""
    try:
        machine = await machines.get_machine(user_id)
        if machine is None:
            return ObservationResult("absent", {})
        permissions = await authorizations.granted_permissions(user_id)
        protection = await metadata.get_value(user_id, DELETION_PROTECTION_KEY)
        description = await metadata.get_value(user_id, DESCRIPTION_KEY)
        mapping = await metadata.get_value(user_id, KEYS_KEY)
        listed = await machines.list_keys(user_id)
    except ProviderError:
        return ObservationResult("unknown", {})
    data: dict[str, Any] = {
        "userState": _STATE.get(machine.state, "inactive"),
        "permissions": sorted(permissions),
        "keys": observed_keys(mapping, listed),
        **deletion_protection(protection),
    }
    token_type = _TOKEN_TYPE.get(machine.access_token_type)
    if token_type is not None:
        data["accessTokenType"] = token_type
    if description:
        data["description"] = description
    return ObservationResult("present", data)


def observed_keys(mapping: str | None, listed: list[IdentityKey]) -> list[dict[str, Any]]:
    """Chaves do `observed`: o mapa `fingerprint -> keyId` cruzado com o `ListKeys`."""
    known = parse_key_mapping(mapping)
    by_id = {key.key_id: key for key in listed}
    keys: list[dict[str, Any]] = []
    for fingerprint, key_id in sorted(known.items()):
        key = by_id.get(key_id)
        if key is None:
            keys.append({"fingerprint": fingerprint, "keyId": key_id, "status": "expired"})
        else:
            item: dict[str, Any] = {
                "fingerprint": fingerprint,
                "keyId": key_id,
                "status": "active",
            }
            if key.expires_at is not None:
                item["expiresAt"] = key.expires_at
            keys.append(item)
    return keys


def parse_key_mapping(mapping: str | None) -> dict[str, str]:
    """O mapa `fingerprint -> keyId` do metadado; ilegível vale vazio."""
    if not mapping:
        return {}
    try:
        loaded = cast("dict[str, Any]", json.loads(mapping))
        return {str(fingerprint): str(key_id) for fingerprint, key_id in loaded.items()}
    except ValueError, AttributeError:
        return {}


def deletion_protection(value: str | None) -> dict[str, bool]:
    """O campo `deletionProtection` do `observed`, a partir do metadado (decisão 0074).

    Metadado ausente ou com outro valor fica fora do `observed`: a decisão o vê como divergência
    e a ação o regrava. Não se inventa um valor que o provedor não tem.
    """
    protected = _PROTECTION.get(value or "")
    return {} if protected is None else {"deletionProtection": protected}
