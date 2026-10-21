"""Execução das operações da Organization no Zitadel (`docs/RESOURCE-CONTROL-LOOP.md` §46).

Compõe os drivers de `executor/drivers/` (um por sub-recurso); não chama o provedor direto.
O Executor escreve a organização e o preparo dela para os usuários (decisão 0081): o Project Grant
do projeto de roles do `ipm` e os papéis das contas do `ipm/user`. Não cria usuários nem autoriza o
dono. Cada operação é idempotente e usa o `resourceId` como ID da organização. `platformAccess`
se traduz no estado da organização: `granted` a mantém ativa e `revoked` a desativa
(`.decisions/0038`); o preparo só é reconciliado com `granted`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ipm_organization.common import user_access as access
from ipm_organization.executor.domain.errors import ActionFailedError
from ipm_organization.executor.domain.identity import IdentityOrganization


class Organizations(Protocol):
    """Driver da organização (`executor/drivers/organization.py`)."""

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None: ...

    async def create_organization(self, organization_id: str, *, name: str) -> bool: ...

    async def rename_organization(self, organization_id: str, *, name: str) -> None: ...

    async def activate_organization(self, organization_id: str) -> None: ...

    async def deactivate_organization(self, organization_id: str) -> None: ...

    async def delete_organization(self, organization_id: str) -> None: ...


class Metadata(Protocol):
    """Driver do metadado do provedor (`executor/drivers/metadata.py`)."""

    async def set_value(self, owner_id: str, key: str, value: str) -> None: ...


class UserAccess(Protocol):
    """Driver do Grant e dos papéis do `ipm/user` (`executor/drivers/user_access.py`)."""

    def organization_resource(self, organization_id: str) -> dict[str, Any]: ...

    def grant_resource(self, organization_id: str) -> dict[str, Any]: ...

    async def grant_roles(self, organization_id: str) -> list[str] | None: ...

    async def create_grant(self, organization_id: str, roles: list[str]) -> bool: ...

    async def update_grant(self, organization_id: str, roles: list[str]) -> None: ...

    async def administrator_roles(
        self, account_id: str, resource: dict[str, Any]
    ) -> frozenset[str] | None: ...

    async def create_administrator(
        self, account_id: str, resource: dict[str, Any], roles: list[str]
    ) -> bool: ...

    async def update_administrator(
        self, account_id: str, resource: dict[str, Any], roles: list[str]
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações da Organization usam."""

    organizations: Organizations
    metadata: Metadata
    user_access: UserAccess


async def execute(
    operation: str,
    organization_id: str,
    desired: Mapping[str, Any],
    drivers: Drivers,
) -> None:
    writer = drivers.organizations
    match operation:
        case "create":
            await _create(organization_id, desired, writer)
            await _ensure_deletion_protection(organization_id, desired, drivers.metadata)
            await _ensure_user_access(organization_id, desired, drivers.user_access)
        case "update":
            await _update(organization_id, desired, writer)
            await _ensure_deletion_protection(organization_id, desired, drivers.metadata)
            await _ensure_user_access(organization_id, desired, drivers.user_access)
        case "delete":
            await writer.delete_organization(organization_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _name_of(desired: Mapping[str, Any]) -> str:
    name = str(desired.get("name", ""))
    if not name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without the name")
    return name


def _wants_access(desired: Mapping[str, Any]) -> bool:
    """`True` para `platformAccess = granted` (organização ativa); `False` para `revoked`."""
    return desired.get("platformAccess") != "revoked"


async def _create(organization_id: str, desired: Mapping[str, Any], writer: Organizations) -> None:
    name = _name_of(desired)
    created = await writer.create_organization(organization_id, name=name)
    if not created:
        # Repetição (retry, reentrega) ou conflito: confere quem é o dono do ID.
        existing = await writer.get_organization(organization_id)
        if existing is None:
            raise ActionFailedError(
                "Rejected", retryable=False, message="organization name already in use"
            )
        if existing.name != name:
            raise ActionFailedError(
                "Rejected", retryable=False, message="organization id in use by another name"
            )
    await _ensure_access(organization_id, desired, writer)


async def _update(organization_id: str, desired: Mapping[str, Any], writer: Organizations) -> None:
    name = _name_of(desired)
    existing = await writer.get_organization(organization_id)
    if existing is None:
        raise ActionFailedError("Rejected", retryable=False, message="organization does not exist")
    if existing.name != name:
        await writer.rename_organization(organization_id, name=name)
    await _ensure_access(organization_id, desired, writer, known=existing)


async def _ensure_access(
    organization_id: str,
    desired: Mapping[str, Any],
    writer: Organizations,
    *,
    known: IdentityOrganization | None = None,
) -> None:
    """Deixa a organização ativa (`granted`) ou desativada (`revoked`), só se for preciso."""
    organization = known or await writer.get_organization(organization_id)
    active = organization.active if organization is not None else True  # recém-criada: ativa
    if _wants_access(desired) and not active:
        await writer.activate_organization(organization_id)
    elif not _wants_access(desired) and active:
        await writer.deactivate_organization(organization_id)


DELETION_PROTECTION_KEY = "deletionProtection"


async def _ensure_deletion_protection(
    resource_id: str, desired: Mapping[str, Any], metadata: Metadata
) -> None:
    """Grava no provedor a proteção contra exclusão do `desired` (decisão 0074).

    Registro sem o campo vale como protegido. A gravação é idempotente: repetir não muda nada.
    """
    protected = desired.get("deletionProtection", True) is not False
    await metadata.set_value(resource_id, DELETION_PROTECTION_KEY, "true" if protected else "false")


async def _ensure_user_access(
    organization_id: str, desired: Mapping[str, Any], driver: UserAccess
) -> None:
    """Deixa a organização pronta para usuários (decisão 0081), só com o que falta.

    O Grant fica com exatamente as roles do `desired`; cada conta do `ipm/user` ganha os papéis que
    lhe faltam, sem perder os que já tem (`UpdateAdministrator` substitui o conjunto, então vai a
    união). O Grant vem antes do papel no Grant. Sem `userAccess`, ou com a organização sem
    acesso, nada é feito.
    """
    if not access.is_managed(desired):
        return
    user_access: Mapping[str, Any] = desired["userAccess"]
    roles = sorted(str(role) for role in user_access["grantRoles"])
    current = await driver.grant_roles(organization_id)
    if current is None:
        if not await driver.create_grant(organization_id, roles):
            await driver.update_grant(organization_id, roles)  # criado por outra tentativa
    elif current != roles:
        await driver.update_grant(organization_id, roles)
    executor = str(user_access["userExecutorAccountId"])
    observer = str(user_access["userObserverAccountId"])
    organization = driver.organization_resource(organization_id)
    for account_id, resource, role in (
        (executor, organization, access.ORGANIZATION_USER_CREATOR),
        (executor, driver.grant_resource(organization_id), access.PROJECT_GRANT_OWNER),
        (observer, organization, access.ORGANIZATION_OWNER_VIEWER),
    ):
        await _ensure_administrator(driver, account_id, resource, role)


async def _ensure_administrator(
    driver: UserAccess, account_id: str, resource: dict[str, Any], role: str
) -> None:
    held = await driver.administrator_roles(account_id, resource)
    if held is None:
        if await driver.create_administrator(account_id, resource, [role]):
            return
        held = await driver.administrator_roles(account_id, resource) or frozenset()
    if role not in held:
        await driver.update_administrator(account_id, resource, sorted(held | {role}))
