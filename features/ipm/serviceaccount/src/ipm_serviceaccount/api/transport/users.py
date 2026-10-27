"""Consulta ao Receiver de User, pelo fluxo normal e com o token do solicitante (decisão 0040).

A service account não lê o banco de outro tipo: pergunta ao Receiver de User se o solicitante é
usuário humano de uma Organization. Qualquer resposta fora do contrato é "não reconhecido".
"""

from typing import cast

import httpx

from ipm_serviceaccount.api.settings import PeersSettings

USERS_PATH = "/v1/ipm/users"
HTTP_OK = 200


class UserPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None:
        try:
            response = await self._client.get(
                f"{self._settings.users_url}{USERS_PATH}/{user_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            return None
        if response.status_code != HTTP_OK:
            return None
        try:
            data: object = response.json()
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        desired = cast("dict[str, object]", data).get("desired")
        if not isinstance(desired, dict):
            return None
        fields = cast("dict[str, object]", desired)
        organization_id = fields.get("organizationId")
        if fields.get("lifecycle") != "present" or not isinstance(organization_id, str):
            return None
        return organization_id
