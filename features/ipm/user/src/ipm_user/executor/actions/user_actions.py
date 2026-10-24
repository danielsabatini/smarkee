"""Execução das operações do usuário da Organization no Zitadel (decisão 0077).

Compõe os drivers de `executor/drivers/` (usuário, autorização e metadado); não chama o provedor
direto. Cada operação é idempotente e usa o `resourceId` como ID do usuário, criado na organização
do cliente (`organizationId`). A criação não envia nem recebe senha: o Zitadel envia o e-mail de
verificação, cuja página também define a senha (um e-mail só). A senha nunca passa por CLI,
Receiver, SSOT nem NATS. As permissões são as do `desired`, exatamente: as que sobrarem no provedor
são revogadas.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from ipm_user.executor.domain.errors import ActionFailedError
from ipm_user.executor.domain.identity import Authorization, IdentityUser


class Users(Protocol):
    """Driver do usuário (`executor/drivers/user.py`)."""

    async def get_user(self, user_id: str) -> IdentityUser | None: ...

    async def create_user(
        self,
        user_id: str,
        *,
        organization_id: str,
        given_name: str,
        family_name: str,
        email: str,
    ) -> bool: ...

    async def delete_user(self, user_id: str) -> None: ...


class Authorizations(Protocol):
    """Driver da autorização em `roles-ipm` (`executor/drivers/authorization.py`)."""

    async def authorization(self, user_id: str, organization_id: str) -> Authorization | None: ...

    async def create(self, user_id: str, organization_id: str, permissions: list[str]) -> None: ...

    async def update(self, authorization_id: str, permissions: list[str]) -> None: ...

    async def remove(self, authorization_id: str) -> None: ...


class Metadata(Protocol):
    """Driver do metadado do provedor (`executor/drivers/metadata.py`)."""

    async def set_value(self, owner_id: str, key: str, value: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações do usuário usam."""

    users: Users
    authorizations: Authorizations
    metadata: Metadata


async def execute(
    operation: str,
    user_id: str,
    desired: Mapping[str, Any],
    drivers: Drivers,
) -> None:
    match operation:
        case "create":
            await _create(user_id, desired, drivers)
            await _ensure_deletion_protection(user_id, desired, drivers.metadata)
        case "update":
            await _update(user_id, desired, drivers)
            await _ensure_deletion_protection(user_id, desired, drivers.metadata)
        case "delete":
            await drivers.users.delete_user(user_id)  # ausente é sucesso idempotente
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
    given_name, family_name, email = (
        str(desired.get("givenName", "")),
        str(desired.get("familyName", "")),
        str(desired.get("email", "")),
    )
    if not (given_name and family_name and email):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the user data"
        )

    created = await drivers.users.create_user(
        user_id,
        organization_id=organization_id,
        given_name=given_name,
        family_name=family_name,
        email=email,
    )
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await drivers.users.get_user(user_id)
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
    await _ensure_permissions(user_id, organization_id, permissions, drivers.authorizations)


async def _update(user_id: str, desired: Mapping[str, Any], drivers: Drivers) -> None:
    organization_id = _organization_of(desired)
    existing = await drivers.users.get_user(user_id)
    if existing is None:
        raise ActionFailedError("Rejected", retryable=False, message="user does not exist")
    if existing.organization_id != organization_id:
        raise ActionFailedError(
            "Rejected", retryable=False, message="user belongs to another organization"
        )
    await _ensure_permissions(
        user_id, organization_id, _permissions_of(desired), drivers.authorizations
    )


async def _ensure_permissions(
    user_id: str, organization_id: str, expected: frozenset[str], authorizations: Authorizations
) -> None:
    """Deixa o usuário com exatamente as permissões do `desired` em `roles-ipm`.

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


DELETION_PROTECTION_KEY = "deletionProtection"


async def _ensure_deletion_protection(
    resource_id: str, desired: Mapping[str, Any], metadata: Metadata
) -> None:
    """Grava no provedor a proteção contra exclusão do `desired` (decisão 0074).

    No usuário da Organization, registro sem o campo vale como desprotegido (decisão 0077). A
    gravação é idempotente: repetir não muda nada.
    """
    protected = desired.get("deletionProtection", False) is True
    await metadata.set_value(resource_id, DELETION_PROTECTION_KEY, "true" if protected else "false")
