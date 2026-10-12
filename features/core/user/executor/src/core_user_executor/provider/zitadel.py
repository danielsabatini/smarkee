"""Cliente de escrita do Zitadel para o Executor (única identidade com escrita, decisão 0014).

Autentica com a conta de serviço `core-user-executor` (papel `ORG_USER_MANAGER`, só a organização
`core`) por assertion JWT. Cada operação é **idempotente**: o `user_id` é o `resourceId`, e a
repetição de um passo já feito é tratada como sucesso (`docs/RESOURCE-CONTROL-LOOP.md` §26).
Os erros viram `ProviderError`, com a causa e se a mesma decisão pode ser tentada de novo.
Nenhum dado pessoal entra em mensagens de erro.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import jwt

from core_user_executor.domain.identity import Grant, ProviderError, ZitadelUser
from core_user_executor.settings import ZitadelSettings

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
TOKEN_SAFETY_SECONDS = 60
NOT_FOUND_CODE = 5  # código gRPC NotFound
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500
ALREADY_EXISTING_ID = "COMMAND-7yiox1isql"  # Errors.User.AlreadyExisting (Zitadel v4.19.4)


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

    # ------------------------------------------------------------------ usuário

    async def get_user(self, user_id: str) -> ZitadelUser | None:
        response = await self._call("GET", f"/v2/users/{user_id}", accept_not_found=True)
        if response is None:
            return None
        user = cast("dict[str, Any]", self._json(response).get("user") or {})
        human = cast("dict[str, Any]", user.get("human") or {})
        email = cast("dict[str, Any]", human.get("email") or {})
        return ZitadelUser(
            email=str(email.get("email", "")), password_set="passwordChanged" in human
        )

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool:
        """Cria o usuário **sem senha**, com o `resourceId` como ID. `False` se já existe."""
        body = {
            "userId": user_id,
            "organization": {"orgId": self._settings.organization_id},
            "username": email,
            "profile": {"givenName": given_name, "familyName": family_name},
            "email": {"email": email},
        }
        try:
            await self._call("POST", "/v2/users/human", body)
        except ProviderError as error:
            if error.reason == "Rejected" and ALREADY_EXISTING_ID in str(error):
                return False
            raise
        return True

    async def send_password_link(self, user_id: str) -> None:
        """Envia o link para a pessoa definir a senha na página do Zitadel."""
        await self._call("POST", f"/v2/users/{user_id}/password_reset", {"sendLink": {}})

    async def delete_user(self, user_id: str) -> None:
        await self._call("DELETE", f"/v2/users/{user_id}", accept_not_found=True)

    # ------------------------------------------------------------------ autorização no projeto

    async def grants(self, user_id: str) -> list[Grant]:
        response = await self._call(
            "POST",
            "/management/v1/users/grants/_search",
            {
                "queries": [
                    {"userIdQuery": {"userId": user_id}},
                    {"projectIdQuery": {"projectId": self._settings.project_id}},
                ]
            },
            organization=True,
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        items = cast("list[dict[str, Any]]", self._json(response).get("result") or [])
        return [
            Grant(
                grant_id=str(item["id"]),
                roles=frozenset(str(r) for r in cast("list[Any]", item.get("roleKeys") or [])),
            )
            for item in items
        ]

    async def create_grant(self, user_id: str, roles: list[str]) -> None:
        await self._call(
            "POST",
            f"/management/v1/users/{user_id}/grants",
            {"projectId": self._settings.project_id, "roleKeys": roles},
            organization=True,
        )

    async def update_grant(self, user_id: str, grant_id: str, roles: list[str]) -> None:
        await self._call(
            "PUT",
            f"/management/v1/users/{user_id}/grants/{grant_id}",
            {"roleKeys": roles},
            organization=True,
        )

    async def remove_grant(self, user_id: str, grant_id: str) -> None:
        await self._call(
            "DELETE",
            f"/management/v1/users/{user_id}/grants/{grant_id}",
            organization=True,
            accept_not_found=True,
        )

    # ------------------------------------------------------------------ HTTP

    async def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        organization: bool = False,
        accept_not_found: bool = False,
    ) -> httpx.Response | None:
        headers = {
            "Host": self._settings.host_header,
            "Authorization": f"Bearer {await self._access_token()}",
        }
        if organization:
            headers["x-zitadel-orgid"] = self._settings.organization_id or ""
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
        return document.get("code") == NOT_FOUND_CODE and bool(document.get("details"))

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
