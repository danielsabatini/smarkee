"""Sessão do sk: token válido sem rede, renovação pelo refresh token e falhas que pedem login."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sk.identity import session as session_module
from sk.identity.credentials import StoredCredentials, load_credentials, save_credentials
from sk.identity.oidc import OidcError, ProviderMetadata, TokenResponse
from sk.identity.session import SessionError, current_access_token

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
METADATA = ProviderMetadata(
    issuer="https://ipm.teste",
    authorization_endpoint="https://ipm.teste/a",
    token_endpoint="https://ipm.teste/t",
    userinfo_endpoint="https://ipm.teste/u",
)


def credentials(
    expires_at: datetime,
    refresh_token: str | None = "refresh-1",  # noqa: S107 (token falso de teste)
) -> StoredCredentials:
    return StoredCredentials(
        issuer=METADATA.issuer,
        client_id="cli",
        token_type="Bearer",
        access_token="access-old",
        access_token_expires_at=expires_at,
        refresh_token=refresh_token,
        id_token="id-old",
        scope="openid offline_access",
        obtained_at=NOW - timedelta(hours=1),
    )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "credentials.json"


def fake_refresh(monkeypatch: pytest.MonkeyPatch, response: TokenResponse | Exception) -> list[str]:
    calls: list[str] = []

    def metadata(issuer: str, *, allow_insecure_http: bool) -> ProviderMetadata:
        return METADATA

    def refresh(metadata: ProviderMetadata, *, client_id: str, refresh_token: str) -> TokenResponse:
        calls.append(refresh_token)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(session_module, "fetch_provider_metadata", metadata)
    monkeypatch.setattr(session_module, "refresh_access_token", refresh)
    return calls


def test_a_token_far_from_expiry_is_returned_without_any_request(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(path, credentials(NOW + timedelta(minutes=10)))
    calls = fake_refresh(monkeypatch, OidcError("não deveria ser chamado"))
    assert current_access_token(path, allow_insecure_http=False, now=NOW) == "access-old"
    assert calls == []


def test_an_expiring_token_is_renewed_and_saved(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(path, credentials(NOW + timedelta(seconds=30)))
    calls = fake_refresh(
        monkeypatch,
        TokenResponse("access-new", "Bearer", 900, "refresh-2", "id-new", "openid"),
    )
    assert current_access_token(path, allow_insecure_http=False, now=NOW) == "access-new"
    assert calls == ["refresh-1"]
    saved = load_credentials(path)
    assert saved.access_token == "access-new"
    assert saved.refresh_token == "refresh-2"
    assert saved.access_token_expires_at == NOW + timedelta(seconds=900)


def test_without_a_new_refresh_token_the_old_one_is_kept(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(path, credentials(NOW - timedelta(minutes=1)))
    fake_refresh(monkeypatch, TokenResponse("access-new", "Bearer", 900, None, None, None))
    current_access_token(path, allow_insecure_http=False, now=NOW)
    saved = load_credentials(path)
    assert saved.refresh_token == "refresh-1"
    assert saved.id_token == "id-old"


def test_an_expired_session_without_refresh_token_asks_for_login(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(path, credentials(NOW - timedelta(minutes=1), refresh_token=None))
    fake_refresh(monkeypatch, OidcError("não deveria ser chamado"))
    with pytest.raises(SessionError, match="sk auth login"):
        current_access_token(path, allow_insecure_http=False, now=NOW)


def test_a_refused_refresh_asks_for_login_without_showing_tokens(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_credentials(path, credentials(NOW - timedelta(minutes=1)))
    fake_refresh(monkeypatch, OidcError("renovação do token: HTTP 400"))
    with pytest.raises(SessionError) as raised:
        current_access_token(path, allow_insecure_http=False, now=NOW)
    assert "refresh-1" not in str(raised.value)
    assert "sk auth login" in str(raised.value)


def test_a_missing_session_asks_for_login(path: Path) -> None:
    with pytest.raises(SessionError, match="sk auth login"):
        current_access_token(path, allow_insecure_http=False, now=NOW)
