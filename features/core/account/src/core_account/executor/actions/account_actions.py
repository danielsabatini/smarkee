"""Execução das operações da Account no Zitadel (`docs/RESOURCE-CONTROL-LOOP.md` §46.1).

Compõe os drivers de `executor/drivers/` (usuário e autorização); não chama o provedor direto.

Cada operação é idempotente e usa o `resourceId` como ID do usuário. A criação não envia nem
recebe senha: ao criar o usuário, o Zitadel envia o e-mail de verificação, cuja página também define
a senha de quem acabou de ser criado (um e-mail só). A senha nunca passa por CLI, Receiver, SSOT
nem NATS.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from core_account.executor.domain.errors import ActionFailedError
from core_account.executor.domain.identity import Grant, IdentityUser


class Users(Protocol):
    """Driver do usuário (`executor/drivers/user.py`)."""

    async def get_user(self, user_id: str) -> IdentityUser | None: ...

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool: ...

    async def delete_user(self, user_id: str) -> None: ...


class Authorizations(Protocol):
    """Driver da autorização nos projetos de permissões (`executor/drivers/authorization.py`)."""

    async def grants(self, user_id: str) -> list[Grant]: ...

    def project_of(self, permission: str) -> str: ...

    async def create_grant(self, user_id: str, project_id: str, permissions: list[str]) -> None: ...

    async def update_grant(self, grant_id: str, permissions: list[str]) -> None: ...

    async def remove_grant(self, grant_id: str) -> None: ...


class Metadata(Protocol):
    """Driver do metadado do provedor (`executor/drivers/metadata.py`)."""

    async def set_value(self, owner_id: str, key: str, value: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações da Account usam."""

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


def _platform_permissions(desired: Mapping[str, Any]) -> frozenset[str]:
    """Permissões de `desired.platformPermissions` (decisão 0025): sem lista própria no Executor."""
    permissions: Any = desired.get("platformPermissions")
    if not isinstance(permissions, list):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the platform permissions"
        )
    return frozenset(str(permission) for permission in cast("list[Any]", permissions))


async def _create(user_id: str, desired: Mapping[str, Any], drivers: Drivers) -> None:
    permissions = _platform_permissions(desired)
    given_name, family_name, email = (
        str(desired.get("givenName", "")),
        str(desired.get("familyName", "")),
        str(desired.get("email", "")),
    )
    if not (given_name and family_name and email):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the account data"
        )

    created = await drivers.users.create_user(
        user_id, given_name=given_name, family_name=family_name, email=email
    )
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await drivers.users.get_user(user_id)
        if existing is None:
            raise ActionFailedError(
                "Rejected", retryable=False, message="email or login name already in use"
            )
        if existing.email.strip().lower() != email.strip().lower():
            raise ActionFailedError(
                "Rejected", retryable=False, message="account id in use by another account"
            )
    await _ensure_grant(user_id, drivers.authorizations, permissions)


async def _update(user_id: str, desired: Mapping[str, Any], drivers: Drivers) -> None:
    if await drivers.users.get_user(user_id) is None:
        raise ActionFailedError("Rejected", retryable=False, message="account does not exist")
    if desired.get("platformAccess") == "revoked":
        for grant in await drivers.authorizations.grants(user_id):
            await drivers.authorizations.remove_grant(grant.grant_id)
        return
    await _ensure_grant(user_id, drivers.authorizations, _platform_permissions(desired))


async def _ensure_grant(
    user_id: str, authorizations: Authorizations, expected: frozenset[str]
) -> None:
    """O usuário tem, em cada projeto, ao menos as permissões de `desired.platformPermissions`.

    Cada permissão vai para o projeto do seu módulo (`authorizations.project_of`); uma autorização
    por projeto.
    """
    if not expected:
        return
    by_project: dict[str, set[str]] = {}
    for permission in sorted(expected):
        by_project.setdefault(authorizations.project_of(permission), set()).add(
            permission
        )  # `ProviderError` se não há projeto
    grants = await authorizations.grants(user_id)
    for project_id, permissions in by_project.items():
        current = next((g for g in grants if g.project_id == project_id), None)
        if current is not None and permissions <= current.permissions:
            continue
        if current is not None:
            await authorizations.update_grant(
                current.grant_id, sorted(permissions | current.permissions)
            )
        else:
            await authorizations.create_grant(user_id, project_id, sorted(permissions))


DELETION_PROTECTION_KEY = "deletionProtection"


async def _ensure_deletion_protection(
    resource_id: str, desired: Mapping[str, Any], metadata: Metadata
) -> None:
    """Grava no provedor a proteção contra exclusão do `desired` (decisão 0074).

    Registro sem o campo vale como protegido. A gravação é idempotente: repetir não muda nada.
    """
    protected = desired.get("deletionProtection", True) is not False
    await metadata.set_value(resource_id, DELETION_PROTECTION_KEY, "true" if protected else "false")
