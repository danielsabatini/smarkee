"""Driver de leitura da organização no Zitadel (`zitadel.org.v2.OrganizationService`).

Espelho do driver de escrita do Executor (`executor/drivers/organization.py`): o mesmo sub-recurso,
só leitura. Só uma consulta bem-sucedida, pelo ID exato, sem resultado é ausência.
"""

from typing import Any, cast

from ipm_organization.observer.domain.identity import IdentityOrganization
from ipm_organization.observer.provider.identity import IdentityConnection

ORGANIZATION_SERVICE = "/zitadel.org.v2.OrganizationService"


class OrganizationDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None:
        """A organização, ou `None` se a consulta pelo ID terminou sem resultado.

        A ausência é uma resposta bem-sucedida e vazia; qualquer erro (permissão, indisponibilidade,
        limite de taxa) vira `ProviderError`, e o chamador o trata como `unknown`.
        """
        response = await self._connection.request(
            "POST",
            f"{ORGANIZATION_SERVICE}/ListOrganizations",
            {"queries": [{"idQuery": {"id": organization_id}}]},
        )
        found = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        for organization in found:
            if organization.get("id") == organization_id:
                return IdentityOrganization(
                    name=str(organization.get("name", "")),
                    state=str(organization.get("state", "")),
                )
        return None
