"""Consulta ao Receiver da Organization, pelo fluxo normal e com o token do solicitante.

O User não lê o banco de outro tipo nem usa credencial própria nele (decisão 0040): pergunta ao
Receiver da Organization se quem chama é o dono dela. Qualquer resposta fora do contrato vira
`AccessCheckError`: na dúvida, o pedido não segue.
"""

from typing import Any, cast

import httpx

from ipm_serviceaccount.receiver.domain.access import AccessCheckError, OrganizationAccess
from ipm_serviceaccount.receiver.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class OrganizationPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess:
        try:
            response = await self._client.get(
                f"{self._settings.organizations_url}{ORGANIZATIONS_PATH}/{organization_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise AccessCheckError(retryable=True) from None
        # O Receiver da Organization responde `404` para Organization de outro dono (não revela a
        # existência) e `403` para quem não tem as permissões do `ipm`.
        if response.status_code in (HTTP_NOT_FOUND, HTTP_FORBIDDEN):
            return OrganizationAccess.NOT_OWNED
        if response.status_code == HTTP_UNAUTHORIZED:
            raise AccessCheckError(retryable=False)
        if response.status_code != HTTP_OK:
            raise AccessCheckError(retryable=True)
        try:
            document = cast("object", response.json())
        except ValueError:
            raise AccessCheckError(retryable=True) from None
        desired: object = (
            cast("dict[str, Any]", document).get("desired") if isinstance(document, dict) else None
        )
        if not isinstance(desired, dict):
            raise AccessCheckError(retryable=True)
        lifecycle = cast("dict[str, Any]", desired).get("lifecycle")
        return OrganizationAccess.OWNED if lifecycle == "present" else OrganizationAccess.NOT_OWNED
