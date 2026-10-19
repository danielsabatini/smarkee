"""Validação dos access tokens do Zitadel para o Receiver de `sum.service` (decisão 0033).

Só valida: assinatura (JWKS), `iss`, `aud` (o projeto de roles do SUM, `roles-sum`)
e `exp`. As roles vêm do claim `urn:zitadel:iam:org:project:<ID do projeto>:roles`.
Sem credencial de escrita no provedor.
"""

import time
from collections.abc import Callable
from typing import Any, cast

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from sum_service.receiver.domain.errors import unauthorized
from sum_service.receiver.domain.principal import Principal
from sum_service.receiver.settings import AuthSettings

ALGORITHMS = ["RS256"]
CLOCK_LEEWAY_SECONDS = 10
MINIMUM_SECONDS_BETWEEN_KEY_REFRESHES = 30


class TokenVerifier:
    """Verifica um access token e devolve o `Principal`."""

    def __init__(
        self,
        settings: AuthSettings,
        client: httpx.AsyncClient,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not settings.audience:
            raise ValueError("a audience (ID do projeto da plataforma) é obrigatória")
        self._settings = settings
        self._audience = settings.audience
        self._client = client
        self._monotonic = monotonic
        self._keys: dict[str, Any] = {}
        self._loaded_at: float | None = None
        self._last_refresh_attempt: float | None = None

    async def verify(self, token: str) -> Principal:
        try:
            # Só lê o `kid` para escolher a chave; a assinatura é verificada em `jwt.decode`.
            header = jwt.get_unverified_header(token)  # NOSONAR python:S5659
        except jwt.InvalidTokenError:
            raise unauthorized() from None
        key_id = header.get("kid")
        if header.get("alg") not in ALGORITHMS or not isinstance(key_id, str):
            raise unauthorized()
        key = await self._key_for(key_id)
        if key is None:
            raise unauthorized()
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self._audience,
                issuer=self._settings.issuer,
                leeway=CLOCK_LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError:
            raise unauthorized() from None
        roles = self._roles(claims)
        return Principal(subject=str(claims["sub"]), roles=roles, access_token=token)

    def _roles(self, claims: dict[str, Any]) -> frozenset[str]:
        roles_claim: object = claims.get(f"urn:zitadel:iam:org:project:{self._audience}:roles")
        if not isinstance(roles_claim, dict):
            return frozenset()
        return frozenset(str(role) for role in cast("dict[object, object]", roles_claim))

    # ------------------------------------------------------------------ chaves

    async def _key_for(self, key_id: str) -> Any | None:
        now = self._monotonic()
        expired = (
            self._loaded_at is None or now - self._loaded_at > self._settings.jwks_cache_seconds
        )
        if expired or key_id not in self._keys:
            await self._refresh(now, force=key_id not in self._keys)
        return self._keys.get(key_id)

    async def _refresh(self, now: float, *, force: bool) -> None:
        # Uma chave desconhecida força a busca, mas no máximo uma vez a cada intervalo mínimo:
        # tokens forjados com `kid` aleatório não podem gerar uma busca por requisição.
        if (
            force
            and self._last_refresh_attempt is not None
            and now - self._last_refresh_attempt < MINIMUM_SECONDS_BETWEEN_KEY_REFRESHES
        ):
            return
        self._last_refresh_attempt = now
        try:
            response = await self._client.get(
                self._settings.jwks_url, headers={"Host": self._settings.host_header}
            )
            response.raise_for_status()
            document = response.json()
        except httpx.HTTPError, ValueError:
            return  # mantém as chaves já conhecidas; a verificação falha para as desconhecidas
        keys: dict[str, Any] = {}
        for entry in document.get("keys", []):
            if entry.get("kty") == "RSA" and isinstance(entry.get("kid"), str):
                keys[entry["kid"]] = RSAAlgorithm.from_jwk(entry)
        if keys:
            self._keys = keys
            self._loaded_at = now
