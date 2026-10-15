"""Cliente somente leitura do Zitadel para o Observer (`docs/RESOURCE-CONTROL-SECURITY.md` §8, §9).

Autentica com a conta de serviço `core-user-observer` (papel `ORG_OWNER_VIEWER`) por assertion JWT.
Toda falha de leitura vira `ProviderError`, e o chamador a trata como `unknown`: erro de leitura
(timeout, 5xx, 401/403, limite de taxa) **nunca** é `absent`. Só um 404 do usuário exato é ausência.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import jwt

from core_user_observer.domain.identity import ProviderError, ZitadelUser
from core_user_observer.settings import ZitadelSettings

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
TOKEN_SAFETY_SECONDS = 60
NOT_FOUND_CODE = 5  # código gRPC NotFound
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
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def get_user(self, user_id: str) -> ZitadelUser | None:
        """O usuário, ou `None` se o Zitadel confirmou (404) que ele não existe."""
        response = await self._request("GET", f"/v2/users/{user_id}")
        if response.status_code == HTTP_NOT_FOUND:
            return None  # `_request` só devolve 404 quando é a ausência inequívoca do usuário
        document = self._json(response)
        user = cast("dict[str, Any]", document.get("user") or {})
        human = cast("dict[str, Any]", user.get("human") or {})
        email = cast("dict[str, Any]", human.get("email") or {})
        return ZitadelUser(
            state=str(user.get("state", "")),
            email_verified=email.get("isVerified") is True,
            password_set="passwordChanged" in human,
        )

    async def granted_roles(self, user_id: str) -> set[str]:
        """União das roles do usuário em todos os projetos de roles (API v2 de autorizações).

        Há um projeto de roles por módulo (decisão 0032); a leitura é pela organização `register`,
        sem filtrar o projeto, para o Observer não depender da lista de módulos.
        """
        response = await self._request(
            "POST",
            "/zitadel.authorization.v2.AuthorizationService/ListAuthorizations",
            {
                "filters": [
                    {"inUserIds": {"ids": [user_id]}},
                    {"organizationId": {"id": self._settings.register_organization_id}},
                ]
            },
        )
        roles: set[str] = set()
        authorizations = cast(
            "list[dict[str, Any]]", self._json(response).get("authorizations") or []
        )
        for authorization in authorizations:
            roles.update(
                str(cast("dict[str, Any]", role)["key"])
                for role in cast("list[Any]", authorization.get("roles") or [])
            )
        return roles

    # ------------------------------------------------------------------ HTTP

    async def _request(
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
        if response.status_code == HTTP_NOT_FOUND and self._is_user_not_found(response):
            return response  # ausência confirmada do usuário exato
        if response.status_code >= HTTP_BAD_REQUEST:
            raise ProviderError(f"HTTP {response.status_code}")
        return response

    @staticmethod
    def _is_user_not_found(response: httpx.Response) -> bool:
        """404 do Zitadel para o usuário (código 5 com detalhe do erro de consulta).

        Um 404 sem o detalhe (caminho errado, proxy) é inconclusivo, e não ausência.
        """
        try:
            body = cast("object", response.json())
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        document = cast("dict[str, Any]", body)
        return document.get("code") == NOT_FOUND_CODE and bool(document.get("details"))

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            document = response.json()
        except ValueError:
            raise ProviderError("invalid JSON") from None
        if not isinstance(document, dict):
            raise ProviderError("unexpected response")
        return cast("dict[str, Any]", document)

    async def _access_token(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._token_expires_at - TOKEN_SAFETY_SECONDS:
            return self._token
        try:
            key = json.loads(Path(self._settings.key_file).read_text(encoding="utf-8"))
            assertion = jwt.encode(
                {
                    "iss": key["userId"],
                    "sub": key["userId"],
                    "aud": self._settings.issuer,
                    "iat": int(now),
                    "exp": int(now) + 300,
                },
                key["key"],
                algorithm="RS256",
                headers={"kid": key["keyId"]},
            )
        except (OSError, ValueError, KeyError) as error:
            raise ProviderError(f"key unavailable: {type(error).__name__}") from None
        try:
            response = await self._client.post(
                self._settings.base_url + "/oauth/v2/token",
                headers={"Host": self._settings.host_header},
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "scope": SCOPE,
                    "assertion": assertion,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ProviderError(f"token: {type(error).__name__}") from None
        self._token = str(payload["access_token"])
        self._token_expires_at = now + float(payload.get("expires_in", 300))
        return self._token
