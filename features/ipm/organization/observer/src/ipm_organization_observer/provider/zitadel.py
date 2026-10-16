"""Cliente somente leitura do Zitadel para o Observer (`docs/RESOURCE-CONTROL-SECURITY.md` §8, §9).

Autentica com a conta de serviço `ipm-organization-observer` (papel `IAM_OWNER_VIEWER`, de instância
e somente leitura) por assertion JWT.
Toda falha de leitura vira `ProviderError`, e o chamador a trata como `unknown`: erro de leitura
(timeout, 5xx, 401/403, limite de taxa) **nunca** é `absent`. Só uma consulta bem-sucedida, pelo ID
exato, sem resultado é ausência.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import jwt

from ipm_organization_observer.domain.identity import ProviderError, ZitadelOrganization
from ipm_organization_observer.settings import ZitadelSettings

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
TOKEN_SAFETY_SECONDS = 60
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

    async def get_organization(self, organization_id: str) -> ZitadelOrganization | None:
        """A organização, ou `None` se a consulta pelo ID terminou sem resultado.

        A ausência é uma resposta bem-sucedida e vazia; qualquer erro (permissão, indisponibilidade,
        limite de taxa) vira `ProviderError`, e o chamador o trata como `unknown`.
        """
        response = await self._request(
            "POST",
            "/zitadel.org.v2.OrganizationService/ListOrganizations",
            {"queries": [{"idQuery": {"id": organization_id}}]},
        )
        found = cast("list[dict[str, Any]]", self._json(response).get("result") or [])
        for organization in found:
            if organization.get("id") == organization_id:
                return ZitadelOrganization(
                    name=str(organization.get("name", "")),
                    state=str(organization.get("state", "")),
                )
        return None

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
        if response.status_code >= HTTP_BAD_REQUEST:
            raise ProviderError(f"HTTP {response.status_code}")
        return response

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
