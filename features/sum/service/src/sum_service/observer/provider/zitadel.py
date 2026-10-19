"""Leitura do Zitadel para o Observer de `sum.service` (somente leitura, decisão 0033).

Autentica com a conta `sum-service-observer` (papel de leitura na organização `register`, sem
nenhum `PROJECT_GRANT_OWNER`). Nunca concede nem remove nada. Qualquer falha de leitura vira
`ProviderError`, e o chamador a trata como `unknown`: erro de leitura nunca vira `absent`. Só um 404
do usuário exato é ausência.
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from sum_service.common.zitadel import ServiceAccountToken, TokenError
from sum_service.observer.domain.authorization import Authorization, ProviderError
from sum_service.observer.settings import ZitadelSettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
NOT_FOUND_CODE = 5
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400


class ZitadelReader:
    def __init__(
        self,
        settings: ZitadelSettings,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._client = client
        self._token_source = ServiceAccountToken(settings, client, clock=clock)

    async def user_exists(self, user_id: str) -> bool:
        """`False` só se o Zitadel confirmou (404 com detalhe) que o usuário não existe."""
        response = await self._request("GET", f"/v2/users/{user_id}")
        return not (response.status_code == HTTP_NOT_FOUND and _is_not_found(response))

    async def authorizations(self, user_id: str) -> list[Authorization]:
        """Autorizações do usuário nos projetos de roles configurados, na organização `register`."""
        response = await self._request(
            "POST",
            f"{AUTHORIZATION_SERVICE}/ListAuthorizations",
            {
                "filters": [
                    {"inUserIds": {"ids": [user_id]}},
                    {"organizationId": {"id": self._settings.register_organization_id}},
                ]
            },
        )
        configured = set(self._settings.project_ids.values())
        items = cast("list[dict[str, Any]]", _json(response).get("authorizations") or [])
        found: list[Authorization] = []
        for item in items:
            project_id = str(cast("dict[str, Any]", item["project"])["id"])
            if project_id not in configured:
                continue
            roles = frozenset(
                str(cast("dict[str, Any]", role)["key"])
                for role in cast("list[Any]", item.get("roles") or [])
            )
            found.append(Authorization(project_id, roles))
        return found

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
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
        if response.status_code == HTTP_NOT_FOUND and _is_not_found(response):
            return response
        if response.status_code >= HTTP_BAD_REQUEST:
            raise ProviderError(f"HTTP {response.status_code}")
        return response

    async def _access_token(self) -> str:
        try:
            return await self._token_source.get()
        except TokenError as error:
            raise ProviderError(error.detail) from None


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        document = response.json()
    except ValueError:
        raise ProviderError("invalid JSON") from None
    if not isinstance(document, dict):
        raise ProviderError("unexpected response")
    return cast("dict[str, Any]", document)


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
