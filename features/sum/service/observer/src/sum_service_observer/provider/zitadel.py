"""Leitura do Zitadel para o Observer de `sum.service` (somente leitura, decisão 0033).

Autentica com a conta `sum-service-observer` (papel de leitura na organização `register`, sem
nenhum `PROJECT_GRANT_OWNER`). Nunca concede nem remove nada. Qualquer falha de leitura vira
`ProviderError`, e o chamador a trata como `unknown`: erro de leitura nunca vira `absent`. Só um 404
do usuário exato é ausência.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import jwt

from sum_service_observer.settings import ZitadelSettings

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
TOKEN_SAFETY_SECONDS = 60
NOT_FOUND_CODE = 5
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400


class ProviderError(Exception):
    """Leitura do Zitadel falhou. O chamador trata como observação `unknown`."""


@dataclass(frozen=True, slots=True)
class Authorization:
    project_id: str
    roles: frozenset[str]


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
