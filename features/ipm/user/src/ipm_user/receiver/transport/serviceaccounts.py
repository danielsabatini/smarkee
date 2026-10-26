"""Consulta ao Receiver de ServiceAccount, com o token do solicitante (decisões 0040 e 0094).

O User não lê o banco de outro tipo: pergunta ao Receiver de ServiceAccount se quem chama é uma
identidade de máquina e de que Organization. Na dúvida, devolve `None` e o pedido segue como de
quem não é membro (o dono ainda é confirmado pela Organization).
"""

from typing import cast

import httpx

from ipm_user.receiver.settings import PeersSettings

SERVICEACCOUNTS_PATH = "/v1/ipm/serviceaccounts"
HTTP_OK = 200


class ServiceAccountPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_serviceaccount_organization(
        self, serviceaccount_id: str, access_token: str
    ) -> str | None:
        """Organization da service account solicitante, ou `None` quando ele não é uma."""
        try:
            response = await self._client.get(
                f"{self._settings.serviceaccounts_url}{SERVICEACCOUNTS_PATH}/{serviceaccount_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != HTTP_OK:
            return None
        try:
            document: object = response.json()
        except ValueError:
            return None
        if not isinstance(document, dict):
            return None
        desired = cast("dict[str, object]", document).get("desired")
        if not isinstance(desired, dict):
            return None
        fields = cast("dict[str, object]", desired)
        organization_id = fields.get("organizationId")
        if fields.get("lifecycle") != "present" or not isinstance(organization_id, str):
            return None
        return organization_id
