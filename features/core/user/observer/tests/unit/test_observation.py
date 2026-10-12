"""Mapeamento do Zitadel para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

from core_user_observer.domain.identity import ProviderError, ZitadelUser
from core_user_observer.domain.observation import observe, user_state
from core_user_observer.settings import ZitadelSettings

SETTINGS = ZitadelSettings()


class FakeReader:
    def __init__(
        self,
        user: ZitadelUser | None,
        roles: set[str] | None = None,
        error: ProviderError | None = None,
        roles_error: ProviderError | None = None,
    ) -> None:
        self._user, self._roles = user, roles or set()
        self._error, self._roles_error = error, roles_error

    async def get_user(self, user_id: str) -> ZitadelUser | None:
        if self._error:
            raise self._error
        return self._user

    async def granted_roles(self, user_id: str) -> set[str]:
        if self._roles_error:
            raise self._roles_error
        return self._roles


def active(*, password: bool = True, verified: bool = True) -> ZitadelUser:
    return ZitadelUser("USER_STATE_ACTIVE", verified, password)


async def test_absent_user() -> None:
    result = await observe(FakeReader(None), SETTINGS, "u-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_present_with_every_role_is_granted() -> None:
    roles = set(SETTINGS.expected_roles)
    result = await observe(FakeReader(active(), roles), SETTINGS, "u-1")
    assert result.presence == "present"
    assert result.data == {
        "emailVerified": True,
        "userState": "active",
        "platformAccess": "granted",
    }


async def test_missing_roles_are_revoked_and_extra_roles_do_not_matter() -> None:
    partial = set(SETTINGS.expected_roles) - {"user.delete"}
    revoked = await observe(FakeReader(active(), partial), SETTINGS, "u-1")
    assert revoked.data["platformAccess"] == "revoked"
    extra = set(SETTINGS.expected_roles) | {"platform.admin"}
    granted = await observe(FakeReader(active(), extra), SETTINGS, "u-1")
    assert granted.data["platformAccess"] == "granted"


async def test_unactivated_user_is_initial() -> None:
    result = await observe(
        FakeReader(active(password=False, verified=False), set()),
        SETTINGS,
        "u-1",
    )
    assert result.data["userState"] == "initial"
    assert result.data["emailVerified"] is False


async def test_read_failures_are_unknown() -> None:
    for reader in (
        FakeReader(None, error=ProviderError("HTTP 503")),
        FakeReader(active(), roles_error=ProviderError("HTTP 500")),
    ):
        result = await observe(reader, SETTINGS, "u-1")
        assert (result.presence, result.data) == ("unknown", {})


def test_state_mapping() -> None:
    assert user_state(ZitadelUser("USER_STATE_INACTIVE", True, True)) == "inactive"
    assert user_state(ZitadelUser("USER_STATE_LOCKED", True, True)) == "locked"
    assert user_state(ZitadelUser("USER_STATE_ACTIVE", True, False)) == "initial"
    assert user_state(ZitadelUser("USER_STATE_DELETED", True, True)) == "inactive"
