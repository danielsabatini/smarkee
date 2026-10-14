"""Execução das operações do User no Zitadel (`docs/RESOURCE-CONTROL-LOOP.md` §46.1).

Cada operação é idempotente e usa o `resourceId` como ID do usuário. A criação não envia nem
recebe senha: o Zitadel envia o e-mail de verificação, e o link para definir a senha é pedido em
seguida (`password_reset`). A senha nunca passa por CLI, Receiver, SSOT nem NATS.
"""

from collections.abc import Mapping
from typing import Any, Protocol, cast

from core_user_executor.domain.errors import ActionFailedError
from core_user_executor.domain.identity import Grant, ZitadelUser


class Writer(Protocol):
    async def get_user(self, user_id: str) -> ZitadelUser | None: ...

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool: ...

    async def send_password_link(self, user_id: str) -> None: ...

    async def delete_user(self, user_id: str) -> None: ...

    async def grants(self, user_id: str) -> list[Grant]: ...

    async def create_grant(self, user_id: str, roles: list[str]) -> None: ...

    async def update_grant(self, user_id: str, grant_id: str, roles: list[str]) -> None: ...

    async def remove_grant(self, user_id: str, grant_id: str) -> None: ...


async def execute(
    operation: str,
    user_id: str,
    desired: Mapping[str, Any],
    writer: Writer,
) -> None:
    match operation:
        case "create":
            await _create(user_id, desired, writer)
        case "update":
            await _update(user_id, desired, writer)
        case "delete":
            await writer.delete_user(user_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _platform_roles(desired: Mapping[str, Any]) -> frozenset[str]:
    """Roles do `desired.platformRoles` (decisão 0025): o Executor não tem lista própria."""
    roles: Any = desired.get("platformRoles")
    if not isinstance(roles, list):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the platform roles"
        )
    return frozenset(str(role) for role in cast("list[Any]", roles))


async def _create(user_id: str, desired: Mapping[str, Any], writer: Writer) -> None:
    roles = _platform_roles(desired)
    given_name, family_name, email = (
        str(desired.get("givenName", "")),
        str(desired.get("familyName", "")),
        str(desired.get("email", "")),
    )
    if not (given_name and family_name and email):
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without the user data"
        )

    created = await writer.create_user(
        user_id, given_name=given_name, family_name=family_name, email=email
    )
    must_send_link = created
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await writer.get_user(user_id)
        if existing is None:
            raise ActionFailedError(
                "Rejected", retryable=False, message="email or login name already in use"
            )
        if existing.email.strip().lower() != email.strip().lower():
            raise ActionFailedError(
                "Rejected", retryable=False, message="user id in use by another user"
            )
        must_send_link = not existing.password_set
    if must_send_link:
        await writer.send_password_link(user_id)
    await _ensure_grant(user_id, writer, roles)


async def _update(user_id: str, desired: Mapping[str, Any], writer: Writer) -> None:
    if await writer.get_user(user_id) is None:
        raise ActionFailedError("Rejected", retryable=False, message="user does not exist")
    if desired.get("platformAccess") == "revoked":
        for grant in await writer.grants(user_id):
            await writer.remove_grant(user_id, grant.grant_id)
        return
    await _ensure_grant(user_id, writer, _platform_roles(desired))


async def _ensure_grant(user_id: str, writer: Writer, expected: frozenset[str]) -> None:
    """O usuário tem, no projeto da plataforma, ao menos as roles de `desired.platformRoles`."""
    if not expected:
        return
    grants = await writer.grants(user_id)
    if any(expected <= grant.roles for grant in grants):
        return
    if grants:
        await writer.update_grant(user_id, grants[0].grant_id, sorted(expected | grants[0].roles))
        return
    await writer.create_grant(user_id, sorted(expected))
