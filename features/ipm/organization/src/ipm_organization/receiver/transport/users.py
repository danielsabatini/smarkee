"""Consulta ao Receiver do User, pelo fluxo normal e com o token do solicitante (decisão 0040).

A Organization não lê o banco do User nem usa credencial própria nele. Pergunta ao Receiver do
User:

- de que Organization o solicitante é usuário (o próprio registro, lido sem permissão adicional);
- se a Organization ainda tem usuários, antes de removê-la (decisão 0077: só vazia).

Qualquer resposta fora do contrato vira `UsersCheckError`: na dúvida, o pedido não segue.
"""

from typing import Any, cast

import httpx

from ipm_organization.receiver.domain.users import BillingAccountCheckError, UsersCheckError
from ipm_organization.receiver.settings import PeersSettings

USERS_PATH = "/v1/ipm/users"
BILLING_ACCOUNTS_PATH = "/v1/bsm/accounts"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class UserPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def organization_of(self, user_id: str, access_token: str) -> str | None:
        """A Organization de que o solicitante é usuário, ou `None` se ele não é um."""
        response = await self._get(f"{USERS_PATH}/{user_id}", access_token, {})
        if response.status_code == HTTP_NOT_FOUND:
            return None
        desired = self._object(self._document(response).get("desired"))
        if desired.get("lifecycle") != "present":
            return None
        organization_id = desired.get("organizationId")
        return organization_id if isinstance(organization_id, str) else None

    async def has_users(self, organization_id: str, access_token: str) -> bool:
        """`True` enquanto a Organization tiver usuários (os em remoção contam)."""
        response = await self._get(
            USERS_PATH, access_token, {"organizationId": organization_id, "limit": 1}
        )
        if response.status_code == HTTP_NOT_FOUND:
            # O Receiver do User só responde `404` quando não confirma a Organization: não decide.
            raise UsersCheckError(retryable=False)
        items: object = self._document(response).get("items")
        if not isinstance(items, list):
            raise UsersCheckError(retryable=True)
        return bool(cast("list[object]", items))

    async def is_ready_billing_account(self, billing_account_id: str, access_token: str) -> bool:
        """`True` se a Billing Account pertence ao solicitante, está presente e `Ready`."""
        try:
            response = await self._client.get(
                f"{self._settings.billing_accounts_url}{BILLING_ACCOUNTS_PATH}/{billing_account_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise BillingAccountCheckError(retryable=True) from None
        if response.status_code == HTTP_NOT_FOUND:
            return False
        if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            raise BillingAccountCheckError(retryable=False)
        if response.status_code != HTTP_OK:
            raise BillingAccountCheckError(retryable=True)
        try:
            document = cast("object", response.json())
        except ValueError:
            raise BillingAccountCheckError(retryable=True) from None
        if not isinstance(document, dict):
            raise BillingAccountCheckError(retryable=True)
        record = cast("dict[str, Any]", document)
        desired = record.get("desired")
        if not isinstance(desired, dict):
            raise BillingAccountCheckError(retryable=True)
        return bool(
            record.get("phase") == "Ready"
            and cast("dict[str, Any]", desired).get("lifecycle") == "present"
        )

    async def _get(self, path: str, access_token: str, params: dict[str, Any]) -> httpx.Response:
        try:
            response = await self._client.get(
                self._settings.users_url + path,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._settings.timeout_seconds,
            )
        except httpx.HTTPError:
            raise UsersCheckError(retryable=True) from None
        if response.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            raise UsersCheckError(retryable=False)
        if response.status_code not in (HTTP_OK, HTTP_NOT_FOUND):
            raise UsersCheckError(retryable=True)
        return response

    @staticmethod
    def _document(response: httpx.Response) -> dict[str, Any]:
        try:
            document = cast("object", response.json())
        except ValueError:
            raise UsersCheckError(retryable=True) from None
        if not isinstance(document, dict):
            raise UsersCheckError(retryable=True)
        return cast("dict[str, Any]", document)

    @staticmethod
    def _object(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise UsersCheckError(retryable=True)
        return cast("dict[str, Any]", value)
