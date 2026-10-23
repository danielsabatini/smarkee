"""O que depende de um serviço e o que um serviço exige antes de ligar, perguntado ao módulo dono.

O SUM não lê o banco de outro módulo: pergunta ao Receiver dele o que pertence a quem chama, com o
token do solicitante (decisões 0040 e 0082):

- Ao desabilitar `ipm`, consulta as Organizations (`/v1/ipm/organizations`): só desabilita sem
  dependentes.
- Ao habilitar um serviço no SUM, consulta as Billing Accounts (`/v1/bsm/accounts`): exige ao menos
  uma Billing Account convergente (`phase == "Ready"` e `desired.lifecycle == "present"`).

Qualquer resposta que não seja uma listagem válida vira `DependentsCheckError`: na dúvida, o pedido
não segue.
"""

from typing import Any, cast

import httpx

from sum_service.receiver.domain.dependents import DependentsCheckError
from sum_service.receiver.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
BILLING_ACCOUNTS_PATH = "/v1/bsm/accounts"
PAGE_SIZE = 200
HTTP_OK = 200


class PeerDependents:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _endpoint_for(self, service: str) -> str | None:
        if service == "ipm":
            return self._settings.organizations_url + ORGANIZATIONS_PATH
        return None

    async def count(self, service: str, access_token: str) -> int:
        """Quantos recursos do dono dependem do serviço (0 para serviço sem dependentes)."""
        endpoint = self._endpoint_for(service)
        if endpoint is None:
            return 0
        items = await self._list_items(service, endpoint, access_token)
        return len(items)

    async def has_ready_billing_account(self, access_token: str) -> bool:
        """Indica se o solicitante possui ao menos uma Billing Account ativa e convergente."""
        endpoint = self._settings.billing_accounts_url + BILLING_ACCOUNTS_PATH
        items = await self._list_items("bsm", endpoint, access_token)
        for item in items:
            if not isinstance(item, dict):
                continue
            record = cast("dict[str, Any]", item)
            desired = cast("dict[str, Any]", record.get("desired") or {})
            if record.get("phase") == "Ready" and desired.get("lifecycle") == "present":
                return True
        return False

    async def _list_items(self, module: str, endpoint: str, access_token: str) -> list[object]:
        try:
            response = await self._client.get(
                endpoint,
                params={"limit": PAGE_SIZE},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise DependentsCheckError(module, retryable=True) from None
        if response.status_code in (401, 403):
            raise DependentsCheckError(module, retryable=False)
        if response.status_code != HTTP_OK:
            raise DependentsCheckError(module, retryable=True)
        try:
            document = cast("object", response.json())
        except ValueError:
            raise DependentsCheckError(module, retryable=True) from None
        items: object = (
            cast("dict[str, object]", document).get("items") if isinstance(document, dict) else None
        )
        if not isinstance(items, list):
            raise DependentsCheckError(module, retryable=True)
        return cast("list[object]", items)
