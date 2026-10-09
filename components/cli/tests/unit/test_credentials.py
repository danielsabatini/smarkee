import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sk.credentials import (
    CredentialsError,
    StoredCredentials,
    default_credentials_path,
    save_credentials,
)


def make_credentials(access_token: str) -> StoredCredentials:
    return StoredCredentials(
        issuer="https://issuer.example",
        client_id="client-1",
        token_type="Bearer",
        access_token=access_token,
        access_token_expires_at=datetime(2026, 10, 9, 13, 0, tzinfo=UTC),
        refresh_token="refresh-1",
        id_token=None,
        scope="openid offline_access",
        obtained_at=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )


def test_default_path_uses_xdg_config_home() -> None:
    assert default_credentials_path({"XDG_CONFIG_HOME": "/custom"}) == Path(
        "/custom/sk/credentials.json"
    )


def test_default_path_falls_back_to_home_config() -> None:
    assert default_credentials_path({}) == Path.home() / ".config" / "sk" / "credentials.json"


def test_credentials_are_written_with_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "sk" / "credentials.json"
    save_credentials(path, make_credentials("access-1"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) & 0o077 == 0
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "issuer": "https://issuer.example",
        "clientId": "client-1",
        "tokenType": "Bearer",
        "accessToken": "access-1",
        "accessTokenExpiresAt": "2026-10-09T13:00:00+00:00",
        "refreshToken": "refresh-1",
        "idToken": None,
        "scope": "openid offline_access",
        "obtainedAt": "2026-10-09T12:00:00+00:00",
    }


def test_new_login_replaces_previous_credentials_without_leftovers(tmp_path: Path) -> None:
    path = tmp_path / "sk" / "credentials.json"
    save_credentials(path, make_credentials("access-1"))
    path.chmod(0o644)
    save_credentials(path, make_credentials("access-2"))

    assert json.loads(path.read_text(encoding="utf-8"))["accessToken"] == "access-2"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [entry.name for entry in path.parent.iterdir()] == ["credentials.json"]


def test_unwritable_directory_raises_credentials_error(tmp_path: Path) -> None:
    blocked_directory = tmp_path / "blocked"
    blocked_directory.mkdir(mode=0o500)
    try:
        with pytest.raises(CredentialsError, match="não foi possível gravar"):
            save_credentials(blocked_directory / "credentials.json", make_credentials("access-1"))
    finally:
        blocked_directory.chmod(0o700)
