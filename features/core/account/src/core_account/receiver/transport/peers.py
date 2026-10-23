"""Consulta aos outros módulos, pelo fluxo normal e com o token do solicitante.

A Account não lê o banco de outro módulo nem usa credencial própria nele: pergunta a cada Receiver
o que pertence a quem chama (cada um já filtra pelo dono). Qualquer resposta que não seja uma
listagem válida vira `AttachmentCheckError`: na dúvida, a exclusão não segue.
"""

from typing import Any, cast

import httpx

from core_account.receiver.domain.attachments import Attachment, AttachmentCheckError
from core_account.receiver.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
BILLING_ACCOUNTS_PATH = "/v1/bsm/accounts"
SERVICES_PATH = "/v1/sum/services"
PAGE_SIZE = 200
HTTP_OK = 200
HTTP_FORBIDDEN = 403
HTTP_UNAUTHORIZED = 401


class PeerResources:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def of(self, access_token: str) -> list[Attachment]:
        # Sem as roles do `ipm` ou `bsm` (serviço desabilitado), o módulo recusa com `403`. Isso
        # vale como "nenhum recurso": o SUM só deixa desabilitar o serviço sem recursos dele
        # (decisão 0040).
        organizations = await self._items(
            "ipm",
            self._settings.organizations_url + ORGANIZATIONS_PATH,
            access_token,
            forbidden_means_none=True,
        )
        billing_accounts = await self._items(
            "bsm",
            self._settings.billing_accounts_url + BILLING_ACCOUNTS_PATH,
            access_token,
            forbidden_means_none=True,
        )
        services = await self._items(
            "sum", self._settings.services_url + SERVICES_PATH, access_token
        )
        # Uma ligação desligada fica como histórico: só a ligada pertence à conta.
        enabled = [
            item
            for item in services
            if cast("dict[str, Any]", item.get("desired") or {}).get("lifecycle") == "present"
        ]
        found = [
            Attachment("Organization", "Organizations", len(organizations)),
            Attachment("Billing Account", "Billing Accounts", len(billing_accounts)),
            Attachment("serviço habilitado", "serviços habilitados", len(enabled)),
        ]
        return [item for item in found if item.count]

    async def _items(
        self, module: str, url: str, access_token: str, *, forbidden_means_none: bool = False
    ) -> list[dict[str, Any]]:
        try:
            response = await self._client.get(
                url,
                params={"limit": PAGE_SIZE},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise AttachmentCheckError(module, retryable=True) from None
        if response.status_code == HTTP_FORBIDDEN and forbidden_means_none:
            return []
        if response.status_code in (HTTP_FORBIDDEN, HTTP_UNAUTHORIZED):
            raise AttachmentCheckError(module, retryable=False)
        if response.status_code != HTTP_OK:
            raise AttachmentCheckError(module, retryable=True)
        try:
            document = cast("object", response.json())
        except ValueError:
            raise AttachmentCheckError(module, retryable=True) from None
        items: object = (
            cast("dict[str, object]", document).get("items") if isinstance(document, dict) else None
        )
        if not isinstance(items, list):
            raise AttachmentCheckError(module, retryable=True)
        return [
            cast("dict[str, Any]", item)
            for item in cast("list[object]", items)
            if isinstance(item, dict)
        ]
