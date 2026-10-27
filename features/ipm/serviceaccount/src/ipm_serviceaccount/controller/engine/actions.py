"""Execução idempotente das operações da service account no Zitadel (decisões 0094 e 0096).

Compõe os drivers de `drivers/` (máquina, autorização e metadado); não chama o provedor direto.
Cada operação é idempotente e usa o `resourceId` como ID do machine user, criado na organização do
cliente (`organizationId`). Só chaves **públicas** passam por aqui: a privada nasce e fica no
cliente. As permissões são as efetivas (calculadas do catálogo; decisão 0097), exatamente: as que
sobrarem no provedor são revogadas.

Como o Zitadel não devolve a chave pública que recebeu, o metadado `keys` do usuário guarda o mapa
`fingerprint -> keyId`, que a observação cruza com o `ListKeys`.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from ipm_serviceaccount.controller.drivers.authorization import AuthorizationDriver
from ipm_serviceaccount.controller.drivers.metadata import MetadataDriver
from ipm_serviceaccount.controller.drivers.serviceaccount import ServiceAccountDriver
from ipm_serviceaccount.controller.engine.observation import (
    DELETION_PROTECTION_KEY,
    DESCRIPTION_KEY,
    KEYS_KEY,
    parse_key_mapping,
)


class ActionFailedError(Exception):
    def __init__(self, reason: str, *, retryable: bool = False, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message


async def execute(
    operation: str,
    user_id: str,
    desired: Mapping[str, Any],
    permissions: frozenset[str],
    *,
    now: datetime,
    machines: ServiceAccountDriver,
    authorizations: AuthorizationDriver,
    metadata: MetadataDriver,
) -> None:
    match operation:
        case "create":
            await _create(user_id, desired, permissions, machines, authorizations)
            await _ensure_metadata(user_id, desired, metadata)
            await _ensure_keys(user_id, desired, machines, metadata, now)
        case "update":
            await _update(user_id, desired, permissions, machines, authorizations)
            await _ensure_metadata(user_id, desired, metadata)
            await _ensure_keys(user_id, desired, machines, metadata, now)
        case "delete":
            await machines.delete_machine(user_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _organization_of(desired: Mapping[str, Any]) -> str:
    organization_id = str(desired.get("organizationId", ""))
    if not organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the organization"
        )
    return organization_id


async def _create(
    user_id: str,
    desired: Mapping[str, Any],
    permissions: frozenset[str],
    machines: ServiceAccountDriver,
    authorizations: AuthorizationDriver,
) -> None:
    organization_id = _organization_of(desired)
    name = str(desired.get("name", ""))
    if not name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without the name")

    created = await machines.create_machine(
        user_id, organization_id=organization_id, username=user_id, name=name
    )
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await machines.get_machine(user_id)
        if existing is None or existing.organization_id != organization_id:
            raise ActionFailedError(
                "Rejected", retryable=False, message="service account id in use by another user"
            )
    await _ensure_permissions(user_id, organization_id, permissions, authorizations)


async def _update(
    user_id: str,
    desired: Mapping[str, Any],
    permissions: frozenset[str],
    machines: ServiceAccountDriver,
    authorizations: AuthorizationDriver,
) -> None:
    organization_id = _organization_of(desired)
    existing = await machines.get_machine(user_id)
    if existing is None:
        raise ActionFailedError(
            "Rejected", retryable=False, message="service account does not exist"
        )
    if existing.organization_id != organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="service account belongs to another organization"
        )
    await _ensure_permissions(user_id, organization_id, permissions, authorizations)


async def _ensure_permissions(
    user_id: str,
    organization_id: str,
    expected: frozenset[str],
    authorizations: AuthorizationDriver,
) -> None:
    """Deixa a máquina com exatamente as permissões efetivas em `roles-ipm`.

    Uma autorização por máquina: criada quando há permissões, atualizada quando difere e removida
    quando as efetivas não têm nenhuma.
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
    resource_id: str, desired: Mapping[str, Any], metadata: MetadataDriver
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
    user_id: str,
    desired: Mapping[str, Any],
    machines: ServiceAccountDriver,
    metadata: MetadataDriver,
    now: datetime,
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

    stored = await metadata.get_value(user_id, KEYS_KEY)
    mapping = parse_key_mapping(stored)
    present = {key.key_id for key in await machines.list_keys(user_id)}

    for key_id in present - set(mapping.values()):
        await machines.remove_key(user_id, key_id)  # resto sem registro no mapa
    for fingerprint in [fp for fp in mapping if fp not in wanted]:
        await machines.remove_key(user_id, mapping.pop(fingerprint))

    changed = False
    for fingerprint, key in sorted(wanted.items()):
        expires_at = str(key["expiresAt"])
        if fingerprint in mapping and mapping[fingerprint] in present:
            continue
        if _parse_time(expires_at) <= now:
            continue  # vencida: continua no `desired` como `expired`, sem recriar
        mapping[fingerprint] = await machines.add_key(
            user_id, public_key=str(key["publicKey"]), expires_at=expires_at
        )
        changed = True
        await metadata.set_value(user_id, KEYS_KEY, json.dumps(mapping, sort_keys=True))
    if not changed and json.dumps(mapping, sort_keys=True) != (stored or ""):
        await metadata.set_value(user_id, KEYS_KEY, json.dumps(mapping, sort_keys=True))
