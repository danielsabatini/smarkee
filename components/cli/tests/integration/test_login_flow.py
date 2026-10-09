"""Fluxo completo de login contra um provedor OIDC falso, em loopback.

O provedor falso valida o que o Zitadel validaria na troca do código: client_id,
redirect_uri e o code_verifier contra o code_challenge recebido na autorização.
"""

import json
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import cast

import pytest

from sk.oidc import (
    OidcError,
    ProviderMetadata,
    compute_code_challenge,
    fetch_provider_metadata,
    fetch_userinfo,
    run_authorization_code_flow,
)

CLIENT_ID = "client-1"
AUTHORIZATION_CODE = "code-1"
ACCESS_TOKEN = "access-1"


@dataclass
class ProviderState:
    issuer: str = ""
    code_challenge: str | None = None
    redirect_uri: str | None = None
    token_requests: list[dict[str, str]] = field(default_factory=lambda: [])


class _FakeProviderServer(HTTPServer):
    provider_state: ProviderState


class _FakeProviderHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        state = cast(_FakeProviderServer, self.server).provider_state
        if self.path == "/.well-known/openid-configuration":
            self._send_json(
                HTTPStatus.OK,
                {
                    "issuer": state.issuer,
                    "authorization_endpoint": f"{state.issuer}/oauth/v2/authorize",
                    "token_endpoint": f"{state.issuer}/oauth/v2/token",
                    "userinfo_endpoint": f"{state.issuer}/oidc/v1/userinfo",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        elif self.path == "/oidc/v1/userinfo":
            if self.headers.get("Authorization") != f"Bearer {ACCESS_TOKEN}":
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_token"})
                return
            self._send_json(HTTPStatus.OK, {"sub": "user-1", "preferred_username": "alice"})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        state = cast(_FakeProviderServer, self.server).provider_state
        if self.path != "/oauth/v2/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
        state.token_requests.append(form)
        valid_request = (
            form.get("grant_type") == "authorization_code"
            and form.get("code") == AUTHORIZATION_CODE
            and form.get("client_id") == CLIENT_ID
            and form.get("redirect_uri") == state.redirect_uri
            and state.code_challenge is not None
            and compute_code_challenge(form.get("code_verifier", "")) == state.code_challenge
        )
        if not valid_request:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_grant", "error_description": "requisição inválida"},
            )
            return
        self._send_json(
            HTTPStatus.OK,
            {
                "access_token": ACCESS_TOKEN,
                "token_type": "Bearer",
                "expires_in": 43199,
                "refresh_token": "refresh-1",
                "id_token": "id-1",
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def provider() -> Iterator[ProviderState]:
    server = _FakeProviderServer(("127.0.0.1", 0), _FakeProviderHandler)
    server.provider_state = ProviderState(issuer=f"http://127.0.0.1:{server.server_port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.provider_state
    finally:
        server.shutdown()
        server.server_close()


def make_browser(
    provider: ProviderState, *, returned_state: str | None = None
) -> Callable[[str], None]:
    """Simula o navegador: registra o desafio no provedor e chama o redirect em outra thread."""

    def present_authorization_url(authorization_url: str) -> None:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(authorization_url).query))
        provider.code_challenge = query["code_challenge"]
        provider.redirect_uri = query["redirect_uri"]
        callback_query = urllib.parse.urlencode(
            {"code": AUTHORIZATION_CODE, "state": returned_state or query["state"]}
        )
        callback_url = f"{query['redirect_uri']}?{callback_query}"
        threading.Thread(
            target=lambda: urllib.request.urlopen(callback_url).read(), daemon=True
        ).start()

    return present_authorization_url


def test_login_flow_obtains_tokens_and_userinfo(provider: ProviderState) -> None:
    metadata = fetch_provider_metadata(provider.issuer, allow_insecure_http=True)
    token_response = run_authorization_code_flow(
        metadata,
        client_id=CLIENT_ID,
        scopes=("openid", "offline_access"),
        present_authorization_url=make_browser(provider),
        timeout_seconds=5,
    )

    assert token_response.access_token == ACCESS_TOKEN
    assert token_response.refresh_token == "refresh-1"
    assert token_response.expires_in_seconds == 43199
    assert fetch_userinfo(metadata, token_response.access_token)["preferred_username"] == "alice"
    assert len(provider.token_requests) == 1


def test_forged_state_never_reaches_the_token_endpoint(provider: ProviderState) -> None:
    metadata = fetch_provider_metadata(provider.issuer, allow_insecure_http=True)
    with pytest.raises(OidcError, match="state"):
        run_authorization_code_flow(
            metadata,
            client_id=CLIENT_ID,
            scopes=("openid",),
            present_authorization_url=make_browser(provider, returned_state="forged"),
            timeout_seconds=5,
        )
    assert provider.token_requests == []


def test_token_endpoint_error_is_reported_with_provider_description(
    provider: ProviderState,
) -> None:
    metadata = fetch_provider_metadata(provider.issuer, allow_insecure_http=True)
    with pytest.raises(OidcError, match="invalid_grant: requisição inválida"):
        run_authorization_code_flow(
            metadata,
            client_id="wrong-client",
            scopes=("openid",),
            present_authorization_url=make_browser(provider),
            timeout_seconds=5,
        )


def test_discovery_rejects_issuer_mismatch(provider: ProviderState) -> None:
    configured_issuer = provider.issuer
    provider.issuer = "http://other-issuer.example"
    with pytest.raises(OidcError, match="difere do configurado"):
        fetch_provider_metadata(configured_issuer, allow_insecure_http=True)


def test_discovery_rejects_http_issuer_without_permission(provider: ProviderState) -> None:
    with pytest.raises(OidcError, match="sem TLS"):
        fetch_provider_metadata(provider.issuer, allow_insecure_http=False)


def test_userinfo_with_invalid_token_is_reported(provider: ProviderState) -> None:
    metadata = ProviderMetadata(
        issuer=provider.issuer,
        authorization_endpoint=f"{provider.issuer}/oauth/v2/authorize",
        token_endpoint=f"{provider.issuer}/oauth/v2/token",
        userinfo_endpoint=f"{provider.issuer}/oidc/v1/userinfo",
    )
    with pytest.raises(OidcError, match="HTTP 401"):
        fetch_userinfo(metadata, "invalid")
