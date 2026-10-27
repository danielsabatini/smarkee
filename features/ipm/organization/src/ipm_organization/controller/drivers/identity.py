"""Conexão autenticada com o Zitadel para o Controller (decisão 0096).

Transporte autenticado com assertion JWT. Suporta header `x-zitadel-orgid` explícito
para garantir o princípio do menor privilégio (AGENTS.md §4.2, decisão 0096):
operações escopadas à organização utilizam `org_id`, reservando chamadas sem org_id
exclusivamente para operações de instância (como AddOrganization).
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from ipm_organization.common.identity import ServiceAccountToken, TokenError
from ipm_organization.controller.settings import IdentitySettings

NOT_FOUND_CODE = 5
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
HTTP_CONFLICT = 409
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500


class ProviderError(Exception):
    def __init__(self, reason: str, *, retryable: bool = False, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.retryable = retryable
        self.detail = detail


def _classify(status: int) -> ProviderError:
    if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return ProviderError("Unauthorized", retryable=False, detail=f"HTTP {status}")
    if status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR:
        return ProviderError("ProviderUnavailable", retryable=True, detail=f"HTTP {status}")
    return ProviderError("Rejected", retryable=False, detail=f"HTTP {status}")


class IdentityConnection:
    def __init__(
        self,
        settings: IdentitySettings,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._client = client
        self._token_source = ServiceAccountToken(settings, client, clock=clock)

    async def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        accept_not_found: bool = False,
        accept_conflict: bool = False,
        org_id: str | None = None,
    ) -> httpx.Response | None:
        """Executa chamada ao Zitadel. None em 404/409 quando aceitos pelo chamador."""
        headers = {
            "Host": self._settings.host_header,
            "Authorization": f"Bearer {await self._access_token()}",
            "Connect-Protocol-Version": "1",
        }
        if org_id is not None:
            headers["x-zitadel-orgid"] = org_id

        try:
            response = await self._client.request(
                method, self._settings.base_url + path, headers=headers, json=body
            )
        except httpx.HTTPError as error:
            raise ProviderError(
                "ProviderUnavailable", retryable=True, detail=type(error).__name__
            ) from None

        status = response.status_code
        if status == HTTP_NOT_FOUND and accept_not_found and self._is_not_found(response):
            return None
        if status == HTTP_CONFLICT and accept_conflict:
            return None
        if status >= HTTP_BAD_REQUEST:
            error = _classify(status)
            detail = self._error_id(response)
            raise ProviderError(
                error.reason, retryable=error.retryable, detail=detail or f"HTTP {status}"
            )
        return response

    async def call_idempotent(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        already_done_id: str,
        *,
        org_id: str | None = None,
    ) -> None:
        """Chamada cujo resultado já alcançado (código already_done_id) conta como sucesso."""
        try:
            await self.call(method, path, body, org_id=org_id)
        except ProviderError as error:
            if error.reason == "Rejected" and already_done_id in str(error):
                return
            raise

    @staticmethod
    def json(response: httpx.Response) -> dict[str, Any]:
        try:
            document = response.json()
        except ValueError:
            raise ProviderError(
                "ProviderUnavailable", retryable=True, detail="invalid JSON"
            ) from None
        if not isinstance(document, dict):
            raise ProviderError("ProviderUnavailable", retryable=True, detail="unexpected response")
        return cast("dict[str, Any]", document)

    @staticmethod
    def _error_id(response: httpx.Response) -> str:
        try:
            body = cast("object", response.json())
        except ValueError:
            return ""
        if not isinstance(body, dict):
            return ""
        details = cast("list[Any]", cast("dict[str, Any]", body).get("details") or [])
        first = (
            cast("dict[str, Any]", details[0]) if details and isinstance(details[0], dict) else {}
        )
        return str(first.get("id", ""))

    @staticmethod
    def _is_not_found(response: httpx.Response) -> bool:
        if response.status_code != HTTP_NOT_FOUND:
            return False
        try:
            body = response.json()
        except ValueError:
            return True
        if not isinstance(body, dict):
            return True
        document = cast("dict[str, Any]", body)
        return document.get("code") == NOT_FOUND_CODE or "NotFound" in str(
            document.get("message", "")
        )

    async def _access_token(self) -> str:
        try:
            return await self._token_source.get()
        except TokenError as error:
            raise ProviderError(
                "Unauthorized", retryable=False, detail=f"token error: {error.detail}"
            ) from None
