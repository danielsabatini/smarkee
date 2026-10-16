"""Execução das operações da Organization no Zitadel (`docs/RESOURCE-CONTROL-LOOP.md` §46).

O Executor escreve só a organização: não cria usuários, não autoriza o dono e não cria Project
Grant. Cada operação é idempotente e usa o `resourceId` como ID da organização. `platformAccess`
se traduz no estado da organização: `granted` a mantém ativa e `revoked` a desativa
(`.decisions/0038`).
"""

from collections.abc import Mapping
from typing import Any, Protocol

from ipm_organization_executor.domain.errors import ActionFailedError
from ipm_organization_executor.domain.identity import ZitadelOrganization


class Writer(Protocol):
    async def get_organization(self, organization_id: str) -> ZitadelOrganization | None: ...

    async def create_organization(self, organization_id: str, *, name: str) -> bool: ...

    async def rename_organization(self, organization_id: str, *, name: str) -> None: ...

    async def activate_organization(self, organization_id: str) -> None: ...

    async def deactivate_organization(self, organization_id: str) -> None: ...

    async def delete_organization(self, organization_id: str) -> None: ...


async def execute(
    operation: str,
    organization_id: str,
    desired: Mapping[str, Any],
    writer: Writer,
) -> None:
    match operation:
        case "create":
            await _create(organization_id, desired, writer)
        case "update":
            await _update(organization_id, desired, writer)
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


async def _create(organization_id: str, desired: Mapping[str, Any], writer: Writer) -> None:
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


async def _update(organization_id: str, desired: Mapping[str, Any], writer: Writer) -> None:
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
    writer: Writer,
    *,
    known: ZitadelOrganization | None = None,
) -> None:
    """Deixa a organização ativa (`granted`) ou desativada (`revoked`), só se for preciso."""
    organization = known or await writer.get_organization(organization_id)
    active = organization.active if organization is not None else True  # recém-criada: ativa
    if _wants_access(desired) and not active:
        await writer.activate_organization(organization_id)
    elif not _wants_access(desired) and active:
        await writer.deactivate_organization(organization_id)
