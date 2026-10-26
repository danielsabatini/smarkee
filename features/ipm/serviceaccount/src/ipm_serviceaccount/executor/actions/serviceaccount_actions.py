"""Execução das operações da service account da Organization no Zitadel (decisão 0094).

Compõe os drivers de `executor/drivers/` (máquina, autorização e metadado); não chama o provedor
direto. Cada operação é idempotente e usa o `resourceId` como ID do machine user, criado na
organização do cliente (`organizationId`). Só chaves **públicas** passam por aqui: a privada nasce
e fica no cliente. As permissões são as do `desired`, exatamente: as que sobrarem no provedor são
revogadas.

Como o Zitadel não devolve a chave pública que recebeu, o Executor guarda no metadado `keys` do
usuário o mapa `fingerprint -> keyId`; o Observer o cruza com o `ListKeys` (decisão 0094).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from ipm_serviceaccount.executor.domain.errors import ActionFailedError
from ipm_serviceaccount.executor.domain.identity import Authorization, IdentityMachine

DELETION_PROTECTION_KEY = "deletionProtection"
DESCRIPTION_KEY = "description"
KEYS_KEY = "keys"


class Machines(Protocol):
    """Driver da máquina (`executor/drivers/serviceaccount.py`)."""

    async def get_machine(self, user_id: str) -> IdentityMachine | None: ...

    async def create_machine(
        self, user_id: str, *, organization_id: str, username: str, name: str
    ) -> bool: ...

    async def delete_machine(self, user_id: str) -> None: ...

    async def list_key_ids(self, user_id: str) -> set[str]: ...

    async def add_key(self, user_id: str, *, public_key: str, expires_at: str) -> str: ...

    async def remove_key(self, user_id: str, key_id: str) -> None: ...


class Authorizations(Protocol):
    """Driver da autorização em `roles-ipm` (`executor/drivers/authorization.py`)."""

    async def authorization(self, user_id: str, organization_id: str) -> Authorization | None: ...

    async def create(self, user_id: str, organization_id: str, permissions: list[str]) -> None: ...

    async def update(self, authorization_id: str, permissions: list[str]) -> None: ...

    async def remove(self, authorization_id: str) -> None: ...


class Metadata(Protocol):
    """Driver do metadado do provedor (`executor/drivers/metadata.py`)."""

    async def set_value(self, owner_id: str, key: str, value: str) -> None: ...


class MetadataReader(Protocol):
    """Leitura do metadado para conferir o mapa de chaves (`drivers/metadata_reader.py`)."""

    async def get_value(self, owner_id: str, key: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações da service account usam."""

    machines: Machines
    authorizations: Authorizations
    metadata: Metadata
    metadata_reader: MetadataReader


async def execute(
    operation: str,
    user_id: str,
    desired: Mapping[str, Any],
    drivers: Drivers,
    now: datetime | None = None,
) -> None:
    moment = now if now is not None else datetime.now(UTC)
    match operation:
        case "create":
            await _create(user_id, desired, drivers)
            await _ensure_metadata(user_id, desired, drivers.metadata)
            await _ensure_keys(user_id, desired, drivers, moment)
        case "update":
            await _update(user_id, desired, drivers)
            await _ensure_metadata(user_id, desired, drivers.metadata)
            await _ensure_keys(user_id, desired, drivers, moment)
        case "delete":
            await drivers.machines.delete_machine(user_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _organization_of(desired: Mapping[str, Any]) -> str:
    organization_id = str(desired.get("organizationId", ""))
    if not organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the organization"
        )
    return organization_id


def _permissions_of(desired: Mapping[str, Any]) -> frozenset[str]:
    permissions: Any = desired.get("permissions")
    if not isinstance(permissions, list):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the permissions"
        )
    return frozenset(str(permission) for permission in cast("list[Any]", permissions))


async def _create(user_id: str, desired: Mapping[str, Any], drivers: Drivers) -> None:
    organization_id = _organization_of(desired)
    permissions = _permissions_of(desired)
    name = str(desired.get("name", ""))
    if not name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without the name")

    created = await drivers.machines.create_machine(
        user_id, organization_id=organization_id, username=user_id, name=name
    )
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await drivers.machines.get_machine(user_id)
        if existing is None or existing.organization_id != organization_id:
            raise ActionFailedError(
                "Rejected", retryable=False, message="service account id in use by another user"
            )
    await _ensure_permissions(user_id, organization_id, permissions, drivers.authorizations)


async def _update(user_id: str, desired: Mapping[str, Any], drivers: Drivers) -> None:
    organization_id = _organization_of(desired)
    existing = await drivers.machines.get_machine(user_id)
    if existing is None:
        raise ActionFailedError(
            "Rejected", retryable=False, message="service account does not exist"
        )
    if existing.organization_id != organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="service account belongs to another organization"
        )
    await _ensure_permissions(
        user_id, organization_id, _permissions_of(desired), drivers.authorizations
    )


async def _ensure_permissions(
    user_id: str, organization_id: str, expected: frozenset[str], authorizations: Authorizations
) -> None:
    """Deixa a máquina com exatamente as permissões do `desired` em `roles-ipm`.

    Uma autorização por máquina: criada quando há permissões, atualizada quando difere e removida
    quando o `desired` não tem nenhuma.
    """
    current = await authorizations.authorization(user_id, organization_id)
    if current is None:
        if expected:
            await authorizations.create(user_id, organization_id, sorted(expected))
        return
    if not expected:
        await authorizations.remove(current.authorization_id)
    elif current.permissions != expected:
        await authorizations.update(current.authorization_id, sorted(expected))


async def _ensure_metadata(
    resource_id: str, desired: Mapping[str, Any], metadata: Metadata
) -> None:
    """Grava a proteção contra exclusão (0074) e a descrição no metadado do provedor.

    O Zitadel v2 não atualiza a descrição da máquina, então ela vive no metadado `description`.
    Na service account, registro sem o campo vale como protegido (decisão 0094). Gravar de novo
    não muda nada.
    """
    protected = desired.get("deletionProtection", True) is not False
    await metadata.set_value(resource_id, DELETION_PROTECTION_KEY, "true" if protected else "false")
    description = desired.get("description")
    if isinstance(description, str) and description:
        await metadata.set_value(resource_id, DESCRIPTION_KEY, description)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _ensure_keys(
    user_id: str, desired: Mapping[str, Any], drivers: Drivers, now: datetime
) -> None:
    """Deixa no provedor exatamente as chaves públicas do `desired` (por fingerprint).

    Chave a remover: sai do provedor (`RemoveKey`). Chave nova: `AddKey`. Chave vencida no
    `desired` não é recriada (o Zitadel recusaria o vencimento no passado). Uma chave do provedor
    fora do mapa (resto de uma falha entre `AddKey` e a gravação do mapa) é removida.
    """
    raw_keys: Any = desired.get("keys")
    wanted: dict[str, Mapping[str, Any]] = {}
    for item in cast("list[Any]", raw_keys) if isinstance(raw_keys, list) else []:
        if isinstance(item, dict):
            key = cast("dict[str, Any]", item)
            wanted[str(key["fingerprint"])] = key

    stored = await drivers.metadata_reader.get_value(user_id, KEYS_KEY)
    mapping: dict[str, str] = {}
    if stored:
        try:
            loaded = cast("dict[str, Any]", json.loads(stored))
            mapping = {str(fingerprint): str(key_id) for fingerprint, key_id in loaded.items()}
        except ValueError, AttributeError:
            mapping = {}
    present = await drivers.machines.list_key_ids(user_id)

    for key_id in present - set(mapping.values()):
        await drivers.machines.remove_key(user_id, key_id)  # resto sem registro no mapa
    for fingerprint in [fp for fp in mapping if fp not in wanted]:
        await drivers.machines.remove_key(user_id, mapping.pop(fingerprint))

    changed = False
    for fingerprint, key in sorted(wanted.items()):
        expires_at = str(key["expiresAt"])
        if fingerprint in mapping and mapping[fingerprint] in present:
            continue
        if _parse_time(expires_at) <= now:
            continue  # vencida: continua no `desired` como `expired`, sem recriar
        mapping[fingerprint] = await drivers.machines.add_key(
            user_id, public_key=str(key["publicKey"]), expires_at=expires_at
        )
        changed = True
        await drivers.metadata.set_value(user_id, KEYS_KEY, json.dumps(mapping, sort_keys=True))
    if not changed and json.dumps(mapping, sort_keys=True) != (stored or ""):
        await drivers.metadata.set_value(user_id, KEYS_KEY, json.dumps(mapping, sort_keys=True))
