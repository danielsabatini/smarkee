"""Conexão só de leitura com o Zitadel para o Observer de `sum.service` (decisão 0033).

Só o transporte autenticado: a conta `sum-service-observer` (papel de leitura na organização
`register`, sem nenhum `PROJECT_GRANT_OWNER`) por assertion JWT e a chamada HTTP. Nunca concede nem
remove nada. Não conhece recurso: as leituras ficam em `observer/drivers/`, espelhando os drivers de
escrita do Executor.
Qualquer falha de leitura vira `ProviderError`, e o chamador a trata como `unknown`: erro de leitura
nunca vira `absent`.
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from sum_service.common.identity import ServiceAccountToken, TokenError
from sum_service.observer.domain.authorization import ProviderError
from sum_service.observer.settings import IdentitySettings

NOT_FOUND_CODE = 5
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400


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

    async def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        absence_on_not_found: bool = False,
    ) -> httpx.Response | None:
        """A resposta; `None` só no 404 inequívoco, quando o chamador o aceita como ausência."""
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
            raise ProviderError(type(error).__name__) from None
        if (
            absence_on_not_found
            and response.status_code == HTTP_NOT_FOUND
            and _is_not_found(response)
        ):
            return None
        if response.status_code >= HTTP_BAD_REQUEST:
            raise ProviderError(f"HTTP {response.status_code}")
        return response

    @staticmethod
    def json(response: httpx.Response) -> dict[str, Any]:
        try:
            document = response.json()
        except ValueError:
            raise ProviderError("invalid JSON") from None
        if not isinstance(document, dict):
            raise ProviderError("unexpected response")
        return cast("dict[str, Any]", document)

    async def _access_token(self) -> str:
        try:
            return await self._token_source.get()
        except TokenError as error:
            raise ProviderError(error.detail) from None


def _is_not_found(response: httpx.Response) -> bool:
    """404 do Zitadel com o código de NotFound e o detalhe da consulta (não um caminho errado)."""
    try:
        body = cast("object", response.json())
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    document = cast("dict[str, Any]", body)
    return document.get("code") in (NOT_FOUND_CODE, "not_found") and bool(document.get("details"))
