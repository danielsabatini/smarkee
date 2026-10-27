"""Execução idempotente das operações da Organization no Zitadel (decisão 0096)."""

from collections.abc import Mapping
from typing import Any, cast

from ipm_organization.common import user_access as access
from ipm_organization.controller.drivers.metadata import MetadataDriver
from ipm_organization.controller.drivers.organization import (
    IdentityOrganization,
    OrganizationDriver,
)
from ipm_organization.controller.drivers.user_access import UserAccessDriver

DELETION_PROTECTION_KEY = "deletionProtection"


class ActionFailedError(Exception):
    def __init__(self, reason: str, *, retryable: bool = False, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason
        self.retryable = retryable
        self.message = message


async def execute(
    operation: str,
    organization_id: str,
    desired: Mapping[str, Any],
    *,
    organizations: OrganizationDriver,
    metadata: MetadataDriver,
    user_access: UserAccessDriver,
) -> None:
    match operation:
        case "create":
            await _create(organization_id, desired, organizations)
            await _ensure_deletion_protection(organization_id, desired, metadata)
            await _ensure_user_access(organization_id, desired, user_access)
        case "update":
            await _update(organization_id, desired, organizations)
            await _ensure_deletion_protection(organization_id, desired, metadata)
            await _ensure_user_access(organization_id, desired, user_access)
        case "delete":
            await organizations.delete_organization(organization_id)
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _name_of(desired: Mapping[str, Any]) -> str:
    name = str(desired.get("name", ""))
    if not name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without the name")
    return name


def _wants_access(desired: Mapping[str, Any]) -> bool:
    return desired.get("platformAccess") != "revoked"


async def _create(
    organization_id: str, desired: Mapping[str, Any], writer: OrganizationDriver
) -> None:
    name = _name_of(desired)
    created = await writer.create_organization(organization_id, name=name)
    if not created:
        existing = await writer.get_organization(organization_id)
        if existing is None:
            raise ActionFailedError(
                "Rejected", retryable=False, message="organization name already in use"
            )
        if existing.name != name:
            raise ActionFailedError(
                "Rejected", retryable=False, message="organization id in use by another name"
            )
    known: IdentityOrganization | None = None
    if created:
        known = IdentityOrganization(name=name, active=True)
    await _ensure_access(organization_id, desired, writer, known=known)


async def _update(
    organization_id: str, desired: Mapping[str, Any], writer: OrganizationDriver
) -> None:
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
    writer: OrganizationDriver,
    *,
    known: IdentityOrganization | None = None,
) -> None:
    organization = known or await writer.get_organization(organization_id)
    active = organization.active if organization is not None else True
    if _wants_access(desired) and not active:
        await writer.activate_organization(organization_id)
    elif not _wants_access(desired) and active:
        await writer.deactivate_organization(organization_id)


async def _ensure_deletion_protection(
    organization_id: str, desired: Mapping[str, Any], writer: MetadataDriver
) -> None:
    protected = desired.get("deletionProtection", True) is not False
    await writer.set_value(
        organization_id, DELETION_PROTECTION_KEY, "true" if protected else "false"
    )


async def _ensure_user_access(
    organization_id: str, desired: Mapping[str, Any], writer: UserAccessDriver
) -> None:
    if not access.is_managed(desired):
        return
    raw_access = desired.get("userAccess")
    if not isinstance(raw_access, Mapping):
        return
    user_access = cast("Mapping[str, Any]", raw_access)

    permissions = [str(p) for p in cast("list[object]", user_access.get("grantPermissions") or [])]
    created = await writer.create_grant(organization_id, permissions)
    if not created:
        held = await writer.grant_permissions(organization_id)
        if held is not None and sorted(held) != sorted(permissions):
            await writer.update_grant(organization_id, permissions)

    for account_id, required_perms in access.required_administrators(user_access).items():
        grant_perms = sorted(p for p in required_perms if p == access.PROJECT_GRANT_OWNER)
        org_perms = sorted(p for p in required_perms if p != access.PROJECT_GRANT_OWNER)
        if grant_perms:
            await _ensure_admin(
                writer, account_id, writer.grant_resource(organization_id), grant_perms
            )
        if org_perms:
            await _ensure_admin(
                writer, account_id, writer.organization_resource(organization_id), org_perms
            )


async def _ensure_admin(
    writer: UserAccessDriver,
    account_id: str,
    resource: dict[str, Any],
    permissions: list[str],
) -> None:
    created = await writer.create_administrator(account_id, resource, permissions)
    if not created:
        held = await writer.administrator_permissions(account_id, resource)
        if held is not None and not frozenset(permissions) <= held:
            await writer.update_administrator(account_id, resource, sorted(held | set(permissions)))
