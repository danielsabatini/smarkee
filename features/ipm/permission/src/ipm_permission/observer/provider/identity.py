"""Conexão só de leitura com o Zitadel para o Observer (`docs/loop/RESOURCE-CONTROL-SECURITY.md`
§8).

Só o transporte autenticado: a conta de serviço `ipm-permission-observer` (`PROJECT_OWNER_VIEWER`
em cada projeto `roles-<módulo>` e `roles-operator`, mais `ORG_OWNER_VIEWER` nas organizações `core`
e `operator`, sem o qual o Zitadel devolve a lista de roles vazia) por assertion JWT e a chamada
HTTP. Não conhece recurso: as leituras ficam em `observer/drivers/`, espelhando os drivers de
escrita do Executor. Toda falha de leitura vira `ProviderError`, e o chamador a trata como
`unknown`: erro de leitura (timeout, 5xx, 401/403, limite de taxa) **nunca** é `absent`.
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from ipm_permission.common.identity import ServiceAccountToken, TokenError
from ipm_permission.observer.domain.identity import ProviderError
from ipm_permission.observer.settings import IdentitySettings

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
    ) -> httpx.Response:
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
