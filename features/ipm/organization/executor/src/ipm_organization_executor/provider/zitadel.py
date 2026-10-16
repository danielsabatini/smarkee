"""Cliente de escrita do Zitadel para o Executor (única identidade com escrita da Organization).

Autentica com a conta de serviço `ipm-organization-executor` (papel de instância `IAM_ORG_MANAGER`)
por assertion JWT. Cada operação é **idempotente**: o `organization_id` é o `resourceId`, e a
repetição de um passo já feito é tratada como sucesso
(`docs/RESOURCE-CONTROL-LOOP.md` §26).
Os erros viram `ProviderError`, com a causa e se a mesma decisão pode ser tentada de novo.
Nenhum dado do pedido entra em mensagens de erro.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import jwt

from ipm_organization_executor.domain.identity import ProviderError, ZitadelOrganization
from ipm_organization_executor.settings import ZitadelSettings

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
TOKEN_SAFETY_SECONDS = 60
NOT_FOUND_CODE = 5  # código gRPC NotFound
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
HTTP_CONFLICT = 409
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500
ORGANIZATION_SERVICE = "/zitadel.org.v2.OrganizationService"
ACTIVE_STATE = "ORGANIZATION_STATE_ACTIVE"
# Identificadores estáveis dos erros de "já feito" do Zitadel v4.19.4 (a mensagem é localizada).
NOT_CHANGED_ID = "ORG-4VSdf"  # a organização já tem o nome pedido
ALREADY_ACTIVE_ID = "EVENT-bfnrh"
ALREADY_INACTIVE_ID = "EVENT-Dbs2g"


def _classify(status: int, text: str = "") -> ProviderError:
    if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return ProviderError("Unauthorized", retryable=False, detail=f"HTTP {status}")
    if status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR:
        return ProviderError("ProviderUnavailable", retryable=True, detail=f"HTTP {status}")
    return ProviderError("Rejected", retryable=False, detail=f"HTTP {status}")


class ZitadelWriter:
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

    # ------------------------------------------------------------------ organização
    # API v2 de organizações (`zitadel.org.v2.OrganizationService`, verificada na v4.19.4). O
    # `organizationId` informado vira o ID no Zitadel, então repetir a criação não duplica.

    async def get_organization(self, organization_id: str) -> ZitadelOrganization | None:
        response = await self._call(
            "POST",
            f"{ORGANIZATION_SERVICE}/ListOrganizations",
            {"queries": [{"idQuery": {"id": organization_id}}]},
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        found = cast("list[dict[str, Any]]", self._json(response).get("result") or [])
        for organization in found:
            if organization.get("id") == organization_id:
                return ZitadelOrganization(
                    name=str(organization.get("name", "")),
                    active=organization.get("state") == ACTIVE_STATE,
                )
        return None

    async def create_organization(self, organization_id: str, *, name: str) -> bool:
        """Cria a organização com o `resourceId` como ID. `False` se o ID ou o nome já existem."""
        response = await self._call(
            "POST",
            "/v2/organizations",
            {"name": name, "organizationId": organization_id},
            accept_conflict=True,
        )
        return response is not None

    async def rename_organization(self, organization_id: str, *, name: str) -> None:
        await self._call_idempotent(
            "POST", f"/v2/organizations/{organization_id}", {"name": name}, NOT_CHANGED_ID
        )

    async def activate_organization(self, organization_id: str) -> None:
        await self._call_idempotent(
            "POST", f"/v2/organizations/{organization_id}/activate", {}, ALREADY_ACTIVE_ID
        )

    async def deactivate_organization(self, organization_id: str) -> None:
        await self._call_idempotent(
            "POST", f"/v2/organizations/{organization_id}/deactivate", {}, ALREADY_INACTIVE_ID
        )

    async def delete_organization(self, organization_id: str) -> None:
        await self._call("DELETE", f"/v2/organizations/{organization_id}", accept_not_found=True)

    async def _call_idempotent(
        self, method: str, path: str, body: dict[str, Any], already_done_id: str
    ) -> None:
        """Chamada cujo resultado já alcançado (erro `already_done_id`) conta como sucesso."""
        try:
            await self._call(method, path, body)
        except ProviderError as error:
            if error.reason == "Rejected" and already_done_id in str(error):
                return
            raise

    # ------------------------------------------------------------------ HTTP

    async def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        accept_not_found: bool = False,
        accept_conflict: bool = False,
    ) -> httpx.Response | None:
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

    @staticmethod
    def _error_id(response: httpx.Response) -> str:
        """Identificador estável do erro do Zitadel (sem a mensagem, que pode ter dados)."""
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
        # REST gRPC-gateway devolve o código numérico (5); o Connect devolve o texto `not_found`.
        return document.get("code") in (NOT_FOUND_CODE, "not_found") and bool(
            document.get("details")
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
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
            raise ProviderError(
                "Unauthorized", retryable=False, detail=f"key unavailable: {type(error).__name__}"
            ) from None
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
            raise ProviderError(
                "ProviderUnavailable", retryable=True, detail=f"token: {type(error).__name__}"
            ) from None
        self._token = str(payload["access_token"])
        self._token_expires_at = now + float(payload.get("expires_in", 300))
        return self._token
