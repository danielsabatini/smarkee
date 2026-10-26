"""Credencial das contas de serviço no Zitadel: configuração e token de acesso (decisão 0063).

Observer (leitura) e Executor (escrita) autenticam do mesmo modo: *assertion* JWT assinada com a
chave da conta de serviço, trocada por um access token (`docs/RESOURCE-CONTROL-SECURITY.md` §8,
§9). Só isto é comum; o que cada um faz com o token, e como trata os erros, é do papel.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx
import jwt

from ipm_group.common.settings import Section

SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
TOKEN_SAFETY_SECONDS = 60
ASSERTION_LIFETIME_SECONDS = 300


class IdentitySettings(Section):
    base_url: str = "http://localhost:8080"
    """Endereço da API do Zitadel na rede interna (não passa pelo gateway público)."""

    host_header: str = "localhost:8080"
    """`Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo."""

    issuer: str = "http://localhost:8080"
    """Audience da assertion JWT da conta de serviço."""

    key_file: str = "/run/secrets/zitadel-key.json"
    """Chave JSON da conta de serviço do papel (montada só no contêiner dele)."""

    timeout_seconds: float = 5.0


class TokenError(Exception):
    """Não foi possível obter o token. `kind` diz onde: na chave local ou na troca com o Zitadel."""

    def __init__(self, kind: Literal["key", "exchange"], detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class ServiceAccountToken:
    """Access token da conta de serviço, guardado até perto de expirar."""

    def __init__(
        self,
        settings: IdentitySettings,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    async def get(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._expires_at - TOKEN_SAFETY_SECONDS:
            return self._token
        assertion = self._assertion(now)
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
            raise TokenError("exchange", f"token: {type(error).__name__}") from None
        self._token = str(payload["access_token"])
        self._expires_at = now + float(payload.get("expires_in", ASSERTION_LIFETIME_SECONDS))
        return self._token

    def _assertion(self, now: float) -> str:
        try:
            key = json.loads(Path(self._settings.key_file).read_text(encoding="utf-8"))
            return jwt.encode(
                {
                    "iss": key["userId"],
                    "sub": key["userId"],
                    "aud": self._settings.issuer,
                    "iat": int(now),
                    "exp": int(now) + ASSERTION_LIFETIME_SECONDS,
                },
                key["key"],
                algorithm="RS256",
                headers={"kid": key["keyId"]},
            )
        except (OSError, ValueError, KeyError) as error:
            raise TokenError("key", f"key unavailable: {type(error).__name__}") from None
