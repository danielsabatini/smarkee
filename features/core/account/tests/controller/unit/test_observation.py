"""Observação da Account: a leitura que falha vira `unknown`, nunca `absent`."""

from typing import Any

from core_account.controller.drivers.authorization import Grant
from core_account.controller.drivers.identity import ProviderError
from core_account.controller.drivers.user import IdentityUser
from core_account.controller.engine.observation import account_state, observe_account

PERMISSIONS = {"ipm.organization.create", "ipm.organization.get", "core.account.get"}


class FakeReader:
    """Atende aos drivers de usuário e de autorização (leitura)."""

    def __init__(
        self,
        user: IdentityUser | None,
        permissions: set[str] | None = None,
        error: ProviderError | None = None,
        permissions_error: ProviderError | None = None,
    ) -> None:
        self._user, self._permissions = user, permissions or set()
        self._error, self._permissions_error = error, permissions_error

    async def get_user(self, user_id: str) -> IdentityUser | None:
        if self._error:
            raise self._error
        return self._user

    async def grants(self, user_id: str) -> list[Grant]:
        if self._permissions_error:
            raise self._permissions_error
        if not self._permissions:
            return []
        return [Grant("g-1", "p-1", frozenset(self._permissions))]


class FakeMetadata:
    def __init__(self, value: str | None = "true", error: ProviderError | None = None) -> None:
        self._value = value
        self._error = error

    async def get_value(self, owner_id: str, key: str) -> str | None:
        if self._error:
            raise self._error
        return self._value if key == "deletionProtection" else None


def both(fake: FakeReader, metadata: FakeMetadata | None = None) -> dict[str, Any]:
    """O mesmo fake atende aos dois drivers de leitura (usuário e autorização)."""
    return {"users": fake, "authorizations": fake, "metadata": metadata or FakeMetadata()}


async def observe(drivers: dict[str, Any], user_id: str):
    return await observe_account(user_id, **drivers)


def active(*, password: bool = True, verified: bool = True) -> IdentityUser:
    return IdentityUser("a@x.com", "USER_STATE_ACTIVE", verified, password)


async def test_absent_user() -> None:
    result = await observe(both(FakeReader(None)), "u-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_present_reports_the_permissions_the_user_has_sorted() -> None:
    result = await observe(both(FakeReader(active(), set(PERMISSIONS))), "u-1")
    assert result.presence == "present"
    assert result.data == {
        "emailVerified": True,
        "accountState": "active",
        "platformAccess": "granted",
        "platformPermissions": [
            "core.account.get",
            "ipm.organization.create",
            "ipm.organization.get",
        ],
        "deletionProtection": True,
    }


async def test_a_user_without_permissions_is_revoked_with_an_empty_list() -> None:
    result = await observe(both(FakeReader(active(), set())), "u-1")
    assert result.data["platformAccess"] == "revoked"
    assert result.data["platformPermissions"] == []


async def test_extra_permissions_are_reported_as_they_are() -> None:
    result = await observe(both(FakeReader(active(), PERMISSIONS | {"core.account.admin"})), "u-1")
    assert "core.account.admin" in result.data["platformPermissions"]


async def test_unactivated_account_is_initial() -> None:
    result = await observe(
        both(FakeReader(active(password=False, verified=False), set())),
        "u-1",
    )
    assert result.data["accountState"] == "initial"
    assert result.data["emailVerified"] is False


async def test_read_failures_are_unknown() -> None:
    for reader in (
        both(FakeReader(None, error=ProviderError("HTTP 503"))),
        both(FakeReader(active(), permissions_error=ProviderError("HTTP 500"))),
    ):
        result = await observe(reader, "u-1")
        assert (result.presence, result.data) == ("unknown", {})


async def test_deletion_protection_comes_from_the_metadata() -> None:
    """O metadado `deletionProtection` do usuário vira o campo do `observed` (decisão 0074)."""
    result = await observe(
        both(FakeReader(active(), set(PERMISSIONS)), FakeMetadata("false")), "u-1"
    )
    assert result.data["deletionProtection"] is False
    for value in (None, "yes"):
        result = await observe(
            both(FakeReader(active(), set(PERMISSIONS)), FakeMetadata(value)), "u-1"
        )
        assert "deletionProtection" not in result.data


async def test_a_metadata_read_failure_is_unknown() -> None:
    failing = FakeMetadata(error=ProviderError("HTTP 503"))
    result = await observe(both(FakeReader(active(), set(PERMISSIONS)), failing), "u-1")
    assert (result.presence, result.data) == ("unknown", {})


def test_state_mapping() -> None:
    assert account_state(IdentityUser("a@x.com", "USER_STATE_INACTIVE", True, True)) == "inactive"
    assert account_state(IdentityUser("a@x.com", "USER_STATE_LOCKED", True, True)) == "locked"
    assert account_state(IdentityUser("a@x.com", "USER_STATE_ACTIVE", True, False)) == "initial"
    assert account_state(IdentityUser("a@x.com", "USER_STATE_DELETED", True, True)) == "inactive"
