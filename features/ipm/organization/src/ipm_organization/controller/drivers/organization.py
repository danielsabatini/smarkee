"""Driver de leitura e escrita da organização no Zitadel (v4.19.4).

Operações atômicas e idempotentes usando o `resourceId` como ID no Zitadel.
A criação (`create_organization`) é uma chamada de nível de instância (sem org_id).
As demais operações utilizam o header `x-zitadel-orgid` (menor privilégio, decisão 0096).
"""

from dataclasses import dataclass
from typing import Any, cast

from ipm_organization.controller.drivers.identity import IdentityConnection

ORGANIZATION_SERVICE = "/zitadel.org.v2.OrganizationService"
ACTIVE_STATE = "ORGANIZATION_STATE_ACTIVE"
NOT_CHANGED_ID = "ORG-4VSdf"
ALREADY_ACTIVE_ID = "EVENT-bfnrh"
ALREADY_INACTIVE_ID = "EVENT-Dbs2g"


@dataclass(frozen=True, slots=True)
class IdentityOrganization:
    name: str
    active: bool


class OrganizationDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None:
        response = await self._connection.call(
            "POST",
            f"{ORGANIZATION_SERVICE}/ListOrganizations",
            {"queries": [{"idQuery": {"id": organization_id}}]},
            org_id=organization_id,
        )
        assert response is not None  # noqa: S101
        found = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        for organization in found:
            if organization.get("id") == organization_id:
                return IdentityOrganization(
                    name=str(organization.get("name", "")),
                    active=organization.get("state") == ACTIVE_STATE,
                )
        return None

    async def create_organization(self, organization_id: str, *, name: str) -> bool:
        """Cria a organização na instância do Zitadel (AddOrganization). False se já existir."""
        response = await self._connection.call(
            "POST",
            "/v2/organizations",
            {"name": name, "organizationId": organization_id},
            accept_conflict=True,
            org_id=None,  # Chamada de instância explícita
        )
        return response is not None

    async def rename_organization(self, organization_id: str, *, name: str) -> None:
        await self._connection.call_idempotent(
            "POST",
            f"/v2/organizations/{organization_id}",
            {"name": name},
            NOT_CHANGED_ID,
            org_id=organization_id,
        )

    async def activate_organization(self, organization_id: str) -> None:
        await self._connection.call_idempotent(
            "POST",
            f"/v2/organizations/{organization_id}/activate",
            {},
            ALREADY_ACTIVE_ID,
            org_id=organization_id,
        )

    async def deactivate_organization(self, organization_id: str) -> None:
        await self._connection.call_idempotent(
            "POST",
            f"/v2/organizations/{organization_id}/deactivate",
            {},
            ALREADY_INACTIVE_ID,
            org_id=organization_id,
        )

    async def delete_organization(self, organization_id: str) -> None:
        await self._connection.call(
            "DELETE",
            f"/v2/organizations/{organization_id}",
            accept_not_found=True,
            org_id=organization_id,
        )
