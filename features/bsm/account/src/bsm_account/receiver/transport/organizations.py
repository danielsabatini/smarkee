"""Consulta ao Receiver de Organization com o token do solicitante (decisões 0040 e 0082).

A Billing Account não lê o banco de `ipm` nem usa credencial própria nele: pergunta ao Receiver de
Organization se há alguma Organization do solicitante atrelada à Billing Account antes de removê-la.
Sem as roles de `ipm` (serviço `ipm` desabilitado no SUM), o módulo responde `403`, o que equivale a
"nenhuma Organization" (decisão 0040: o SUM só desabilita `ipm` quando não há Organizations).
"""

from typing import Any, cast

import httpx

from bsm_account.receiver.domain.organizations import OrganizationsCheckError
from bsm_account.receiver.settings import PeersSettings

ORGANIZATIONS_PATH = "/v1/ipm/organizations"
PAGE_SIZE = 200
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403


class OrganizationPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def has_organizations(self, billing_account_id: str, access_token: str) -> bool:
        """`True` enquanto alguma Organization do solicitante referenciar `billing_account_id`."""
        try:
            response = await self._client.get(
                self._settings.organizations_url + ORGANIZATIONS_PATH,
                params={"limit": PAGE_SIZE},
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise OrganizationsCheckError(retryable=True) from None
        if response.status_code == HTTP_FORBIDDEN:
            return False
        if response.status_code == HTTP_UNAUTHORIZED:
            raise OrganizationsCheckError(retryable=False)
        if response.status_code != HTTP_OK:
            raise OrganizationsCheckError(retryable=True)
        try:
            document = cast("object", response.json())
        except ValueError:
            raise OrganizationsCheckError(retryable=True) from None
        items: object = (
            cast("dict[str, object]", document).get("items") if isinstance(document, dict) else None
        )
        if not isinstance(items, list):
            raise OrganizationsCheckError(retryable=True)
        for item in cast("list[object]", items):
            if not isinstance(item, dict):
                continue
            desired = cast("dict[str, Any]", item).get("desired")
            if not isinstance(desired, dict):
                continue
            spec = cast("dict[str, Any]", desired)
            if spec.get("billingAccountId") == billing_account_id:
                return True
        return False
