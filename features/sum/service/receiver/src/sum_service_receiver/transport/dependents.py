"""O que depende de um serviço, perguntado ao módulo dono, com o token do solicitante.

O SUM não lê o banco de outro módulo: pergunta ao Receiver dele o que pertence a quem chama. Hoje só
o `ipm` tem dependentes (as Organizations). Qualquer resposta que não seja uma listagem válida vira
`DependentsCheckError`: na dúvida, desabilitar não segue.
"""

from typing import cast

import httpx

from sum_service_receiver.domain.dependents import DependentsCheckError
from sum_service_receiver.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
PAGE_SIZE = 200
HTTP_OK = 200


class PeerDependents:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def count(self, service: str, access_token: str) -> int:
        """Quantos recursos do dono dependem do serviço (0 para serviço sem dependentes)."""
        if service != "ipm":
            return 0
        try:
            response = await self._client.get(
                self._settings.organizations_url + ORGANIZATIONS_PATH,
                params={"limit": PAGE_SIZE},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise DependentsCheckError(service, retryable=True) from None
        if response.status_code in (401, 403):
            raise DependentsCheckError(service, retryable=False)
        if response.status_code != HTTP_OK:
            raise DependentsCheckError(service, retryable=True)
        try:
            document = cast("object", response.json())
        except ValueError:
            raise DependentsCheckError(service, retryable=True) from None
        items: object = (
            cast("dict[str, object]", document).get("items") if isinstance(document, dict) else None
        )
        if not isinstance(items, list):
            raise DependentsCheckError(service, retryable=True)
        return len(cast("list[object]", items))
