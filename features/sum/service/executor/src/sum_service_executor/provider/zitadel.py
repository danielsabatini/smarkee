"""Cliente de escrita do Zitadel para o Executor de `sum.service` (decisões 0032 e 0033).

Autentica com a conta de serviço `sum-service-executor` por assertion JWT. Seu papel é
`PROJECT_GRANT_OWNER` só no Project Grant de `roles-ipm` (decisão 0032). O Zitadel nega
qualquer outra concessão: um Executor comprometido não concede roles de outro módulo, nem cria
usuário.

Cada operação é idempotente: repetir uma concessão já feita é sucesso, e revogar algo que não
existe também. Erros viram `ProviderError`, com a causa e se a decisão pode ser tentada de novo.
Nenhum dado pessoal entra em mensagens de erro.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import jwt

from sum_service_executor.settings import ZitadelSettings

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
TOKEN_SAFETY_SECONDS = 60
NOT_FOUND_CODE = 5
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500
ALREADY_EXISTING_AUTHORIZATION_ID = "V3-DKcYh"  # autorização já existe (Zitadel v4.19.4)


class ProviderError(Exception):
    """A chamada ao Zitadel falhou. `reason` e `retryable` seguem o contrato `failed`."""

    def __init__(self, reason: str, *, retryable: bool, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class Grant:
    """Autorização do usuário num projeto de roles (uma por projeto)."""

    grant_id: str
    project_id: str
    roles: frozenset[str]


def module_of(role: str) -> str:
    return role.split(".", 1)[0]


class ZitadelGranter:
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

    def project_of(self, role: str) -> str:
        """Projeto de roles do módulo da role. Módulo sem projeto configurado: recusa explícita."""
        project_id = self._settings.project_ids.get(module_of(role))
        if project_id is None:
            raise ProviderError(
                "Rejected", retryable=False, detail=f"no roles project for module {module_of(role)}"
            )
        return project_id

    async def grants(self, user_id: str) -> list[Grant]:
        """Autorizações do usuário nos projetos configurados, na organização `register`."""
        response = await self._call(
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
        items = cast("list[dict[str, Any]]", response.get("authorizations") or [])
        return [
            Grant(
                grant_id=str(item["id"]),
                project_id=str(cast("dict[str, Any]", item["project"])["id"]),
                roles=frozenset(
                    str(cast("dict[str, Any]", role)["key"])
                    for role in cast("list[Any]", item.get("roles") or [])
                ),
            )
            for item in items
            if str(cast("dict[str, Any]", item["project"])["id"]) in configured
        ]

    async def create_grant(self, user_id: str, project_id: str, roles: list[str]) -> None:
        try:
            await self._call(
                "POST",
                f"{AUTHORIZATION_SERVICE}/CreateAuthorization",
                {
                    "userId": user_id,
                    "projectId": project_id,
                    "organizationId": self._settings.register_organization_id,
                    "roleKeys": roles,
                },
            )
        except ProviderError as error:
            if error.reason == "Rejected" and ALREADY_EXISTING_AUTHORIZATION_ID in str(error):
                return
            raise

    async def update_grant(self, grant_id: str, roles: list[str]) -> None:
        """Substitui a lista de roles da autorização."""
        await self._call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/UpdateAuthorization",
            {"id": grant_id, "roleKeys": roles},
        )

    async def remove_grant(self, grant_id: str) -> None:
        await self._call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/DeleteAuthorization",
            {"id": grant_id},
            accept_not_found=True,
        )

    async def _call(
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
        return self._json(response)

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


def _reason(status: int) -> str:
    if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return "Unauthorized"
    if status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR:
        return "ProviderUnavailable"
    return "Rejected"


def _retryable(status: int) -> bool:
    return status == HTTP_TOO_MANY_REQUESTS or status >= HTTP_SERVER_ERROR
