"""Consulta ao Receiver de Billing Account (`bsm/account`, decisão 0082).

Confirma se a Billing Account informada na admissão da Organization existe, pertence ao solicitante
e está ativa (`phase == 'Ready'`).
"""

from typing import Any, cast

import httpx

from ipm_organization.api.domain.users import BillingAccountCheckError
from ipm_organization.api.settings import PeersSettings

BILLING_ACCOUNTS_PATH = "/v1/bsm/accounts"
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


class BillingAccountPeer:
    def __init__(self, settings: PeersSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

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
