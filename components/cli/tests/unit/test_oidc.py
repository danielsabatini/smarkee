import threading
import urllib.parse
import urllib.request

import pytest

from sk.oidc import (
    LoopbackReceiver,
    OidcError,
    ProviderMetadata,
    build_authorization_url,
    compute_code_challenge,
    create_pkce_pair,
    ensure_secure_url,
    extract_authorization_code,
)

METADATA = ProviderMetadata(
    issuer="https://issuer.example",
    authorization_endpoint="https://issuer.example/oauth/v2/authorize",
    token_endpoint="https://issuer.example/oauth/v2/token",
    userinfo_endpoint="https://issuer.example/oidc/v1/userinfo",
)


def test_code_challenge_matches_rfc_7636_appendix_b() -> None:
    assert (
        compute_code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_pkce_pair_is_fresh_and_within_rfc_length() -> None:
    first_pair = create_pkce_pair()
    second_pair = create_pkce_pair()
    assert 43 <= len(first_pair.code_verifier) <= 128
    assert first_pair.code_challenge == compute_code_challenge(first_pair.code_verifier)
    assert first_pair.code_verifier != second_pair.code_verifier


def test_https_is_accepted() -> None:
    ensure_secure_url("https://issuer.example", allow_insecure_http=False)


def test_http_is_refused_by_default() -> None:
    with pytest.raises(OidcError, match="sem TLS"):
        ensure_secure_url("http://issuer.example", allow_insecure_http=False)


def test_http_is_accepted_when_explicitly_allowed() -> None:
    ensure_secure_url("http://issuer.example", allow_insecure_http=True)


def test_unsupported_scheme_is_refused_even_when_http_is_allowed() -> None:
    with pytest.raises(OidcError, match="não suportado"):
        ensure_secure_url("file:///etc/passwd", allow_insecure_http=True)


def test_authorization_url_carries_pkce_and_state() -> None:
    authorization_url = build_authorization_url(
        METADATA,
        client_id="client-1",
        redirect_uri="http://127.0.0.1:5000/callback",
        scopes=("openid", "offline_access"),
        state="state-1",
        code_challenge="challenge-1",
    )
    split_url = urllib.parse.urlsplit(authorization_url)
    query = dict(urllib.parse.parse_qsl(split_url.query))
    assert f"{split_url.scheme}://{split_url.netloc}{split_url.path}" == (
        METADATA.authorization_endpoint
    )
    assert query == {
        "response_type": "code",
        "client_id": "client-1",
        "redirect_uri": "http://127.0.0.1:5000/callback",
        "scope": "openid offline_access",
        "state": "state-1",
        "code_challenge": "challenge-1",
        "code_challenge_method": "S256",
    }


def test_authorization_code_is_returned_when_state_matches() -> None:
    assert (
        extract_authorization_code({"code": "code-1", "state": "state-1"}, expected_state="state-1")
        == "code-1"
    )


def test_state_mismatch_is_rejected_before_anything_else() -> None:
    with pytest.raises(OidcError, match="state"):
        extract_authorization_code(
            {"error": "access_denied", "state": "other"}, expected_state="state-1"
        )


def test_non_ascii_state_is_rejected() -> None:
    with pytest.raises(OidcError, match="state"):
        extract_authorization_code({"code": "code-1", "state": "ç"}, expected_state="state-1")


def test_provider_error_is_reported() -> None:
    with pytest.raises(OidcError, match="access_denied: negado"):
        extract_authorization_code(
            {"error": "access_denied", "error_description": "negado", "state": "state-1"},
            expected_state="state-1",
        )


def test_missing_code_is_rejected() -> None:
    with pytest.raises(OidcError, match="código de autorização"):
        extract_authorization_code({"state": "state-1"}, expected_state="state-1")


def test_loopback_receiver_listens_on_ipv4_loopback_with_ephemeral_port() -> None:
    with LoopbackReceiver() as receiver:
        split_uri = urllib.parse.urlsplit(receiver.redirect_uri)
        assert split_uri.hostname == "127.0.0.1"
        assert split_uri.port is not None and split_uri.port > 0
        assert split_uri.path == "/callback"


def test_loopback_receiver_captures_callback_parameters() -> None:
    with LoopbackReceiver() as receiver:
        callback_url = f"{receiver.redirect_uri}?code=code-1&state=state-1"
        browser = threading.Thread(target=lambda: urllib.request.urlopen(callback_url).read())
        browser.start()
        parameters = receiver.wait_for_callback(timeout_seconds=5)
        browser.join(timeout=5)
    assert parameters == {"code": "code-1", "state": "state-1"}


def test_loopback_receiver_times_out() -> None:
    with LoopbackReceiver() as receiver, pytest.raises(OidcError, match="tempo esgotado"):
        receiver.wait_for_callback(timeout_seconds=0.2)
