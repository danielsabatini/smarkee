"""Driver de escrita da organização no Zitadel (`zitadel.org.v2.OrganizationService`, v4.19.4).

Um sub-recurso, operações pequenas e idempotentes: o `organization_id` é o `resourceId` e vira o
ID no Zitadel, então repetir a criação não duplica, e a repetição de um passo já feito é sucesso
(`docs/RESOURCE-CONTROL-LOOP.md` §26). O driver não decide o que fazer: isso é das `actions/`.
"""

from typing import Any, cast

from ipm_organization.executor.domain.identity import IdentityOrganization
from ipm_organization.executor.provider.identity import IdentityConnection

ORGANIZATION_SERVICE = "/zitadel.org.v2.OrganizationService"
ACTIVE_STATE = "ORGANIZATION_STATE_ACTIVE"
# Identificadores estáveis dos erros de "já feito" do Zitadel v4.19.4 (a mensagem é localizada).
NOT_CHANGED_ID = "ORG-4VSdf"  # a organização já tem o nome pedido
ALREADY_ACTIVE_ID = "EVENT-bfnrh"
ALREADY_INACTIVE_ID = "EVENT-Dbs2g"


class OrganizationDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None:
        response = await self._connection.call(
            "POST",
            f"{ORGANIZATION_SERVICE}/ListOrganizations",
            {"queries": [{"idQuery": {"id": organization_id}}]},
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        found = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        for organization in found:
            if organization.get("id") == organization_id:
                return IdentityOrganization(
                    name=str(organization.get("name", "")),
                    active=organization.get("state") == ACTIVE_STATE,
                )
        return None

    async def create_organization(self, organization_id: str, *, name: str) -> bool:
        """Cria a organização com o `resourceId` como ID. `False` se o ID ou o nome já existem."""
        response = await self._connection.call(
            "POST",
            "/v2/organizations",
            {"name": name, "organizationId": organization_id},
            accept_conflict=True,
        )
        return response is not None

    async def rename_organization(self, organization_id: str, *, name: str) -> None:
        await self._connection.call_idempotent(
            "POST", f"/v2/organizations/{organization_id}", {"name": name}, NOT_CHANGED_ID
        )

    async def activate_organization(self, organization_id: str) -> None:
        await self._connection.call_idempotent(
            "POST", f"/v2/organizations/{organization_id}/activate", {}, ALREADY_ACTIVE_ID
        )

    async def deactivate_organization(self, organization_id: str) -> None:
        await self._connection.call_idempotent(
            "POST", f"/v2/organizations/{organization_id}/deactivate", {}, ALREADY_INACTIVE_ID
        )

    async def delete_organization(self, organization_id: str) -> None:
        await self._connection.call(
            "DELETE", f"/v2/organizations/{organization_id}", accept_not_found=True
        )
