"""Observação pura e estruturada do estado real da Organization no Zitadel.

Lê organização, metadados e preparo de usuários, compondo o payload `observed`.
"""

from dataclasses import dataclass
from typing import Any

from ipm_organization.controller.drivers.metadata import MetadataDriver
from ipm_organization.controller.drivers.organization import OrganizationDriver
from ipm_organization.controller.drivers.user_access import UserAccessDriver

DELETION_PROTECTION_KEY = "deletionProtection"


@dataclass(frozen=True, slots=True)
class ObservationResult:
    presence: str
    """'present', 'absent' ou 'unknown'."""
    data: dict[str, Any]


async def observe_organization(
    organization_id: str,
    *,
    organizations: OrganizationDriver,
    metadata: MetadataDriver,
    user_access: UserAccessDriver,
) -> ObservationResult:
    org = await organizations.get_organization(organization_id)
    if org is None:
        return ObservationResult(presence="absent", data={})

    deletion_protection_raw = await metadata.get_value(organization_id, DELETION_PROTECTION_KEY)
    deletion_protection = deletion_protection_raw == "true"

    grant_perms = await user_access.grant_permissions(organization_id)
    admins = await user_access.list_administrators(organization_id)

    user_access_data: dict[str, Any] = {"administrators": admins}
    if grant_perms is not None:
        user_access_data["grantPermissions"] = grant_perms

    return ObservationResult(
        presence="present",
        data={
            "name": org.name,
            "platformAccess": "granted" if org.active else "revoked",
            "organizationState": "active" if org.active else "inactive",
            "deletionProtection": deletion_protection,
            "userAccess": user_access_data,
        },
    )
