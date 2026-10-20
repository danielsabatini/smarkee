"""Conexão de escrita com o Zitadel para o Executor de `sum.service` (decisões 0032 e 0033).

Só o transporte autenticado: a conta de serviço `sum-service-executor` por assertion JWT, a chamada
HTTP e a classificação dos erros. Seu papel é `PROJECT_GRANT_OWNER` só no Project Grant de
`roles-ipm` (decisão 0032): o Zitadel nega qualquer outra concessão, e um Executor comprometido não
concede roles de outro módulo nem cria usuário. Não conhece recurso: as operações ficam em
`executor/drivers/`.
Erros viram `ProviderError`, com a causa e se a decisão pode ser tentada de novo. Nenhum dado
pessoal entra em mensagens de erro.
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from sum_service.common.identity import ServiceAccountToken, TokenError
from sum_service.executor.domain.identity import ProviderError
from sum_service.executor.settings import IdentitySettings

NOT_FOUND_CODE = 5
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500


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
    ) -> dict[str, Any]:
        headers = {
            "Host": self._settings.host_header,
            "Authorization": f"Bearer {await self._access_token()}",
            "Connect-Protocol-Version": "1",
        }
        try:
            response = await self._client.request(
                method, self._settings.base_url + path, headers=headers, json=body
            )
        except httpx.HTTPError as error:
            raise ProviderError(
                "ProviderUnavailable", retryable=True, detail=type(error).__name__
            ) from None
        status = response.status_code
        if status == 404 and accept_not_found and self._is_not_found(response):
            return {}
        if status >= HTTP_BAD_REQUEST:
            detail = self._error_id(response)
            raise ProviderError(
                _reason(status), retryable=_retryable(status), detail=detail or f"HTTP {status}"
            )
        return self.json(response)

    @staticmethod
    def _error_id(response: httpx.Response) -> str:
        """Identificador estável do erro (sem a mensagem, que pode ter dados)."""
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
        try:
            body = cast("object", response.json())
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        document = cast("dict[str, Any]", body)
        # REST gRPC devolve o código numérico (5); o Connect devolve o texto `not_found`.
        return document.get("code") in (NOT_FOUND_CODE, "not_found") and bool(
            document.get("details")
        )

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

    async def _access_token(self) -> str:
        try:
            return await self._token_source.get()
        except TokenError as error:
            if error.kind == "key":
                raise ProviderError("Unauthorized", retryable=False, detail=error.detail) from None
            raise ProviderError(
                "ProviderUnavailable", retryable=True, detail=error.detail
            ) from None


def _reason(status: int) -> str:
    if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return "Unauthorized"
    if status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR:
        return "ProviderUnavailable"
    return "Rejected"


def _retryable(status: int) -> bool:
    return status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR
