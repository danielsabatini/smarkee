"""Execução idempotente das operações do usuário da Organization no Zitadel (decisões 0077 e 0096).

Compõe os drivers de `drivers/` (usuário, autorização e metadado); não chama o provedor direto.
Cada operação é idempotente e usa o `resourceId` como ID do usuário, criado na organização do
cliente (`organizationId`). A criação não envia nem recebe senha: o Zitadel envia o e-mail de
verificação, cuja página também define a senha (um e-mail só). A senha nunca passa por CLI,
Receiver, SSOT nem NATS. As permissões são as efetivas (calculadas do catálogo; decisão 0097),
exatamente: as que sobrarem no provedor são revogadas.
"""

import json
from collections.abc import Mapping
from typing import Any, cast

from ipm_user.controller.drivers.authorization import AuthorizationDriver
from ipm_user.controller.drivers.metadata import MetadataDriver
from ipm_user.controller.drivers.user import UserDriver
from ipm_user.controller.engine.observation import DELETION_PROTECTION_KEY, GROUPS_METADATA_KEY


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
    users: UserDriver,
    authorizations: AuthorizationDriver,
    metadata: MetadataDriver,
) -> None:
    match operation:
        case "create":
            await _create(user_id, desired, permissions, users, authorizations)
            await _ensure_metadata(user_id, desired, metadata)
        case "update":
            await _update(user_id, desired, permissions, users, authorizations)
            await _ensure_metadata(user_id, desired, metadata)
        case "delete":
            await users.delete_user(user_id)  # ausente é sucesso idempotente
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
    users: UserDriver,
    authorizations: AuthorizationDriver,
) -> None:
    organization_id = _organization_of(desired)
    given_name, family_name, email = (
        str(desired.get("givenName", "")),
        str(desired.get("familyName", "")),
        str(desired.get("email", "")),
    )
    if not (given_name and family_name and email):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the user data"
        )

    created = await users.create_user(
        user_id,
        organization_id=organization_id,
        given_name=given_name,
        family_name=family_name,
        email=email,
    )
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await users.get_user(user_id)
        if existing is None:
            raise ActionFailedError(
                "Rejected", retryable=False, message="email or login name already in use"
            )
        if (
            existing.email.strip().lower() != email.strip().lower()
            or existing.organization_id != organization_id
        ):
            raise ActionFailedError(
                "Rejected", retryable=False, message="user id in use by another user"
            )
    await _ensure_permissions(user_id, organization_id, permissions, authorizations)


async def _update(
    user_id: str,
    desired: Mapping[str, Any],
    permissions: frozenset[str],
    users: UserDriver,
    authorizations: AuthorizationDriver,
) -> None:
    organization_id = _organization_of(desired)
    existing = await users.get_user(user_id)
    if existing is None:
        raise ActionFailedError("Rejected", retryable=False, message="user does not exist")
    if existing.organization_id != organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="user belongs to another organization"
        )
    await _ensure_permissions(user_id, organization_id, permissions, authorizations)


async def _ensure_permissions(
    user_id: str,
    organization_id: str,
    expected: frozenset[str],
    authorizations: AuthorizationDriver,
) -> None:
    """Deixa o usuário com exatamente as permissões efetivas em `roles-ipm`.

    Uma autorização por usuário: criada quando há permissões, atualizada quando difere e removida
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
    resource_id: str, desired: Mapping[str, Any], metadata: MetadataDriver
) -> None:
    """Grava a proteção contra exclusão (0074) e os grupos (0088) no metadado do provedor.

    No usuário da Organization, registro sem o campo de proteção vale como desprotegido
    (decisão 0077). Os grupos vão como JSON de lista de slugs ordenada. Gravar de novo não muda
    nada.
    """
    protected = desired.get("deletionProtection", False) is True
    await metadata.set_value(resource_id, DELETION_PROTECTION_KEY, "true" if protected else "false")
    raw_groups = desired.get("groups")
    groups: list[str] = (
        sorted({str(g) for g in cast("list[object]", raw_groups)})
        if isinstance(raw_groups, list)
        else []
    )
    await metadata.set_value(resource_id, GROUPS_METADATA_KEY, json.dumps(groups))
