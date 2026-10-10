import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from core.api.auth import EmailVerification, TokenVerifier
from core.api.errors import ApiError
from core.api.principal import Principal
from core.settings import AuthSettings

ISSUER = "http://issuer.example"
PROJECT_ID = "394490764261851138"
ROLES_CLAIM = f"urn:zitadel:iam:org:project:{PROJECT_ID}:roles"


def make_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_of(key: rsa.RSAPrivateKey, key_id: str) -> dict[str, Any]:
    document = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**document, "kid": key_id, "use": "sig", "alg": "RS256"}


def make_token(
    key: rsa.RSAPrivateKey, *, key_id: str = "key-1", overrides: dict[str, Any] | None = None
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": [PROJECT_ID],
        "sub": "user-1",
        "iat": now,
        "exp": now + 600,
        ROLES_CLAIM: {"organization.create": {"org-1": "core.example"}, "user.get": {"org-1": "x"}},
    }
    claims.update(overrides or {})
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": key_id})


@dataclass
class Provider:
    """Provedor de identidade simulado: JWKS e userinfo."""

    keys: list[dict[str, Any]]
    userinfo: dict[str, Any] = field(default_factory=lambda: {"email_verified": True})
    fail: bool = False
    requests: list[httpx.Request] = field(default_factory=lambda: [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(503)
        if request.url.path.endswith("/keys"):
            return httpx.Response(200, json={"keys": self.keys})
        return httpx.Response(200, json=self.userinfo)


def settings() -> AuthSettings:
    return AuthSettings(
        issuer=ISSUER,
        jwks_url="http://provider.internal/oauth/v2/keys",
        userinfo_url="http://provider.internal/oidc/v1/userinfo",
        host_header="issuer.example",
        audience=PROJECT_ID,
    )


def verifier_for(provider: Provider, clock: list[float] | None = None) -> TokenVerifier:
    client = httpx.AsyncClient(transport=httpx.MockTransport(provider.handler))
    ticks = clock if clock is not None else [0.0]
    return TokenVerifier(settings(), client, monotonic=lambda: ticks[0])


async def test_valid_token_yields_subject_and_roles() -> None:
    key = make_key()
    provider = Provider([jwk_of(key, "key-1")])
    principal = await verifier_for(provider).verify(make_token(key))
    assert principal.subject == "user-1"
    assert principal.roles == {"organization.create", "user.get"}
    assert provider.requests[0].headers["host"] == "issuer.example"


async def test_missing_roles_claim_means_no_roles() -> None:
    key = make_key()
    token = make_token(key, overrides={ROLES_CLAIM: None})
    principal = await verifier_for(Provider([jwk_of(key, "key-1")])).verify(token)
    assert principal.roles == frozenset()


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": ["outro-projeto"]},
        {"iss": "http://outro-emissor"},
        {"exp": int(time.time()) - 3600},
        {"sub": None},
    ],
    ids=["audience", "issuer", "expired", "no-subject"],
)
async def test_invalid_claims_are_unauthorized(overrides: dict[str, Any]) -> None:
    key = make_key()
    token = make_token(key, overrides=overrides)
    if overrides.get("sub", "x") is None:
        now = int(time.time())
        token = jwt.encode(
            {"iss": ISSUER, "aud": [PROJECT_ID], "exp": now + 600}, key, "RS256", {"kid": "key-1"}
        )
    with pytest.raises(ApiError) as raised:
        await verifier_for(Provider([jwk_of(key, "key-1")])).verify(token)
    assert raised.value.status == 401


async def test_token_signed_by_another_key_is_unauthorized() -> None:
    trusted, attacker = make_key(), make_key()
    with pytest.raises(ApiError):
        await verifier_for(Provider([jwk_of(trusted, "key-1")])).verify(make_token(attacker))


@pytest.mark.parametrize("token", ["", "abc", "a.b.c"])
async def test_garbage_is_unauthorized(token: str) -> None:
    with pytest.raises(ApiError):
        await verifier_for(Provider([])).verify(token)


async def test_hmac_and_unsigned_tokens_are_refused() -> None:
    key = make_key()
    provider = Provider([jwk_of(key, "key-1")])
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": [PROJECT_ID], "sub": "x", "exp": now + 60}
    hmac_token = jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": "key-1"})
    none_token = (
        ".".join(
            base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()
            for part in ({"alg": "none", "kid": "key-1", "typ": "JWT"}, claims)
        )
        + "."
    )
    for token in (hmac_token, none_token):
        with pytest.raises(ApiError):
            await verifier_for(provider).verify(token)


async def test_unknown_key_id_refreshes_keys_at_most_once_per_interval() -> None:
    trusted, attacker = make_key(), make_key()
    provider = Provider([jwk_of(trusted, "key-1")])
    clock = [0.0]
    verifier = verifier_for(provider, clock)
    forged = make_token(attacker, key_id="forged")

    for _ in range(3):
        with pytest.raises(ApiError):
            await verifier.verify(forged)
    assert len(provider.requests) == 1

    clock[0] = 60.0
    with pytest.raises(ApiError):
        await verifier.verify(forged)
    assert len(provider.requests) == 2


async def test_rotated_key_is_picked_up() -> None:
    old, new = make_key(), make_key()
    provider = Provider([jwk_of(old, "key-1")])
    clock = [0.0]
    verifier = verifier_for(provider, clock)
    await verifier.verify(make_token(old))
    provider.keys = [jwk_of(old, "key-1"), jwk_of(new, "key-2")]
    clock[0] = 31.0
    principal = await verifier.verify(make_token(new, key_id="key-2"))
    assert principal.subject == "user-1"


async def test_provider_outage_makes_unknown_keys_unauthorized_but_keeps_known_ones() -> None:
    key = make_key()
    provider = Provider([jwk_of(key, "key-1")])
    clock = [0.0]
    verifier = verifier_for(provider, clock)
    await verifier.verify(make_token(key))
    provider.fail = True
    clock[0] = 1000.0  # cache expirado: tenta renovar, falha, mantém as chaves conhecidas
    assert (await verifier.verify(make_token(key))).subject == "user-1"


def test_audience_is_required() -> None:
    with pytest.raises(ValueError, match="audience"):
        TokenVerifier(AuthSettings(), httpx.AsyncClient())


def principal() -> Principal:
    return Principal(subject="user-1", roles=frozenset(), access_token="token-1")


async def test_email_verification_caches_only_positive_results() -> None:
    provider = Provider([], userinfo={"email_verified": True})
    clock = [0.0]
    checker = EmailVerification(
        settings(),
        httpx.AsyncClient(transport=httpx.MockTransport(provider.handler)),
        monotonic=lambda: clock[0],
    )
    assert await checker.is_verified(principal())
    assert await checker.is_verified(principal())
    assert len(provider.requests) == 1
    assert provider.requests[0].headers["authorization"] == "Bearer token-1"
    clock[0] = 301.0
    assert await checker.is_verified(principal())
    assert len(provider.requests) == 2

    provider.userinfo = {"email_verified": False}
    other = Principal(subject="user-2", roles=frozenset(), access_token="token-2")
    assert not await checker.is_verified(other)
    assert not await checker.is_verified(other)
    assert len(provider.requests) == 4  # negativo não é guardado


async def test_email_verification_fails_closed_on_errors() -> None:
    provider = Provider([], fail=True)
    checker = EmailVerification(
        settings(), httpx.AsyncClient(transport=httpx.MockTransport(provider.handler))
    )
    assert not await checker.is_verified(principal())
