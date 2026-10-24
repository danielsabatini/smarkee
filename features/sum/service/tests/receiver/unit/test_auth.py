"""Verificação de token do Receiver de `sum.service`: assinatura, `iss`, `aud` e `exp`.

A audience é o projeto de roles do SUM (`roles-sum`). Um token de outro projeto, mesmo assinado pelo
mesmo provedor, não serve para este Receiver (decisão 0033).
"""

import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from sum_service.receiver.auth.tokens import TokenVerifier
from sum_service.receiver.domain.errors import ApiError
from sum_service.receiver.settings import AuthSettings

ISSUER = "http://ipm-dev.smarkee.com.br:8080"
ROLES_SUM = "394490764261851139"
ROLES_OTHER = "394490764261851138"
KID = "key-1"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(KEY.public_key()))
    jwk["kid"] = KID
    return {"keys": [jwk]}


def _token(
    audience: str = ROLES_SUM,
    issuer: str = ISSUER,
    lifetime: int = 300,
    roles: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "sub": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
        "aud": audience,
        "iat": now,
        "exp": now + lifetime,
    }
    if roles is not None:
        claims[f"urn:zitadel:iam:org:project:{ROLES_SUM}:roles"] = roles
    pem = KEY.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": KID})


def _verifier() -> TokenVerifier:
    def route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_jwks())

    settings = AuthSettings(issuer=ISSUER, audience=ROLES_SUM, jwks_url="http://keys/jwks")
    return TokenVerifier(settings, httpx.AsyncClient(transport=httpx.MockTransport(route)))


async def test_a_token_for_this_project_yields_its_permissions() -> None:
    principal = await _verifier().verify(_token(roles={"sum.ipm.get": {}}))
    assert principal.permissions == frozenset({"sum.ipm.get"})


async def test_a_token_for_another_project_is_unauthorized() -> None:
    with pytest.raises(ApiError) as raised:
        await _verifier().verify(_token(audience=ROLES_OTHER))
    assert raised.value.status.value == 401


async def test_a_token_from_another_issuer_is_unauthorized() -> None:
    with pytest.raises(ApiError):
        await _verifier().verify(_token(issuer="http://outro.exemplo"))


async def test_an_expired_token_is_unauthorized() -> None:
    with pytest.raises(ApiError):
        await _verifier().verify(_token(lifetime=-3600))
