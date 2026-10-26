"""Resultado de uma observação: mapeia o Zitadel para o contrato `observed` da service account.

O Zitadel não devolve a chave pública que recebeu. O Executor guarda no metadado `keys` o mapa
`fingerprint -> keyId`; aqui ele é cruzado com o `ListKeys` para dar a cada chave o `status`:
`active` (listada) ou `expired` (no mapa, mas já fora da lista do provedor). Decisão 0094.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol, cast

from ipm_serviceaccount.observer.domain.identity import (
    IdentityKey,
    IdentityMachine,
    ProviderError,
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


class Machines(Protocol):
    """Driver de leitura da máquina (`observer/drivers/serviceaccount.py`)."""

    async def get_machine(self, user_id: str) -> IdentityMachine | None: ...

    async def list_keys(self, user_id: str) -> list[IdentityKey]: ...


class Authorizations(Protocol):
    """Driver de leitura da autorização em `roles-ipm` (`observer/drivers/authorization.py`)."""

    async def granted_permissions(self, user_id: str) -> set[str]: ...


class Metadata(Protocol):
    """Driver de leitura do metadado do provedor (`observer/drivers/metadata.py`)."""

    async def get_value(self, owner_id: str, key: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    machines: Machines
    authorizations: Authorizations
    metadata: Metadata


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(drivers: Drivers, user_id: str) -> Observation:
    """Lê a máquina, as permissões e as chaves. Falha de leitura é `unknown`, nunca `absent`.

    `permissions` são as que a máquina tem em `roles-ipm`, pelo Project Grant da Organization.
    Quem compara com o `desired` é o Reconciler.
    """
    try:
        machine = await drivers.machines.get_machine(user_id)
        if machine is None:
            return Observation("absent", {})
        permissions = await drivers.authorizations.granted_permissions(user_id)
        protection = await drivers.metadata.get_value(user_id, DELETION_PROTECTION_KEY)
        description = await drivers.metadata.get_value(user_id, DESCRIPTION_KEY)
        mapping = await drivers.metadata.get_value(user_id, KEYS_KEY)
        listed = await drivers.machines.list_keys(user_id)
    except ProviderError:
        return Observation("unknown", {})
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
    return Observation("present", data)


def observed_keys(mapping: str | None, listed: list[IdentityKey]) -> list[dict[str, Any]]:
    """Chaves do `observed`: o mapa `fingerprint -> keyId` cruzado com o `ListKeys`."""
    known: dict[str, str] = {}
    if mapping:
        try:
            loaded = cast("dict[str, Any]", json.loads(mapping))
            known = {str(fingerprint): str(key_id) for fingerprint, key_id in loaded.items()}
        except ValueError, AttributeError:
            known = {}
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
    `resourceId` da máquina: a Organization dela não entra no log do Observer.
    """
    return {}
