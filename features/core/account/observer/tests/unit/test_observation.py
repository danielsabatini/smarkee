"""Mapeamento do Zitadel para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

from core_account_observer.domain.identity import ProviderError, ZitadelUser
from core_account_observer.domain.observation import account_state, observe

ROLES = {"ipm.organization.create", "ipm.organization.get", "core.account.get"}


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
    result = await observe(FakeReader(None), "u-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_present_reports_the_roles_the_user_has_sorted() -> None:
    result = await observe(FakeReader(active(), set(ROLES)), "u-1")
    assert result.presence == "present"
    assert result.data == {
        "emailVerified": True,
        "accountState": "active",
        "platformAccess": "granted",
        "platformRoles": ["core.account.get", "ipm.organization.create", "ipm.organization.get"],
    }


async def test_a_user_without_roles_is_revoked_with_an_empty_list() -> None:
    result = await observe(FakeReader(active(), set()), "u-1")
    assert result.data["platformAccess"] == "revoked"
    assert result.data["platformRoles"] == []


async def test_extra_roles_are_reported_as_they_are() -> None:
    result = await observe(FakeReader(active(), ROLES | {"core.account.admin"}), "u-1")
    assert "core.account.admin" in result.data["platformRoles"]


async def test_unactivated_account_is_initial() -> None:
    result = await observe(
        FakeReader(active(password=False, verified=False), set()),
        "u-1",
    )
    assert result.data["accountState"] == "initial"
    assert result.data["emailVerified"] is False


async def test_read_failures_are_unknown() -> None:
    for reader in (
        FakeReader(None, error=ProviderError("HTTP 503")),
        FakeReader(active(), roles_error=ProviderError("HTTP 500")),
    ):
        result = await observe(reader, "u-1")
        assert (result.presence, result.data) == ("unknown", {})


def test_state_mapping() -> None:
    assert account_state(ZitadelUser("USER_STATE_INACTIVE", True, True)) == "inactive"
    assert account_state(ZitadelUser("USER_STATE_LOCKED", True, True)) == "locked"
    assert account_state(ZitadelUser("USER_STATE_ACTIVE", True, False)) == "initial"
    assert account_state(ZitadelUser("USER_STATE_DELETED", True, True)) == "inactive"
