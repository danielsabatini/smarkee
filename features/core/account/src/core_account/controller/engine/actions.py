"""Execução idempotente das operações da Account no Zitadel (decisões 0014 e 0096).

Compõe os drivers de `drivers/` (usuário, autorização e metadado); não chama o provedor direto.
Cada operação é idempotente e usa o `resourceId` como ID do usuário. A criação não envia nem recebe
senha: ao criar o usuário, o Zitadel envia o e-mail de verificação, cuja página também define a
senha de quem acabou de ser criado (um e-mail só). A senha nunca passa por CLI, API, SSOT nem NATS.
"""

from collections.abc import Mapping
from typing import Any, cast

from core_account.controller.drivers.authorization import AuthorizationDriver
from core_account.controller.drivers.metadata import MetadataDriver
from core_account.controller.drivers.user import UserDriver
from core_account.controller.engine.observation import DELETION_PROTECTION_KEY


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
    *,
    users: UserDriver,
    authorizations: AuthorizationDriver,
    metadata: MetadataDriver,
) -> None:
    match operation:
        case "create":
            await _create(user_id, desired, users, authorizations)
            await _ensure_deletion_protection(user_id, desired, metadata)
        case "update":
            await _update(user_id, desired, users, authorizations)
            await _ensure_deletion_protection(user_id, desired, metadata)
        case "delete":
            await users.delete_user(user_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _platform_permissions(desired: Mapping[str, Any]) -> frozenset[str]:
    """Permissões de `desired.platformPermissions` (decisão 0025), sem lista própria."""
    permissions: Any = desired.get("platformPermissions")
    if not isinstance(permissions, list):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the platform permissions"
        )
    return frozenset(str(permission) for permission in cast("list[Any]", permissions))


async def _create(
    user_id: str,
    desired: Mapping[str, Any],
    users: UserDriver,
    authorizations: AuthorizationDriver,
) -> None:
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

    created = await users.create_user(
        user_id, given_name=given_name, family_name=family_name, email=email
    )
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await users.get_user(user_id)
        if existing is None:
            raise ActionFailedError(
                "Rejected", retryable=False, message="email or login name already in use"
            )
        if existing.email.strip().lower() != email.strip().lower():
            raise ActionFailedError(
                "Rejected", retryable=False, message="account id in use by another account"
            )
    await _ensure_grant(user_id, authorizations, permissions)


async def _update(
    user_id: str,
    desired: Mapping[str, Any],
    users: UserDriver,
    authorizations: AuthorizationDriver,
) -> None:
    if await users.get_user(user_id) is None:
        raise ActionFailedError("Rejected", retryable=False, message="account does not exist")
    if desired.get("platformAccess") == "revoked":
        for grant in await authorizations.grants(user_id):
            await authorizations.remove_grant(grant.grant_id)
        return
    await _ensure_grant(user_id, authorizations, _platform_permissions(desired))


async def _ensure_grant(
    user_id: str, authorizations: AuthorizationDriver, expected: frozenset[str]
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


async def _ensure_deletion_protection(
    resource_id: str, desired: Mapping[str, Any], metadata: MetadataDriver
) -> None:
    """Grava no provedor a proteção contra exclusão do `desired` (decisão 0074).

    Registro sem o campo vale como protegido. A gravação é idempotente: repetir não muda nada.
    """
    protected = desired.get("deletionProtection", True) is not False
    await metadata.set_value(resource_id, DELETION_PROTECTION_KEY, "true" if protected else "false")
