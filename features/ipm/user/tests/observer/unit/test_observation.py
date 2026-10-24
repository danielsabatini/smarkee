"""Mapeamento do Zitadel para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

from ipm_user.observer.domain.identity import IdentityUser, ProviderError
from ipm_user.observer.domain.observation import (
    Drivers,
    log_identifiers,
    observe,
    user_state,
)

PERMISSIONS = {"ipm.user.get", "ipm.organization.get", "ipm.user.create"}


class FakeReader:
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

    async def granted_permissions(self, user_id: str) -> set[str]:
        if self._permissions_error:
            raise self._permissions_error
        return self._permissions


class FakeMetadata:
    def __init__(self, value: str | None = "true", error: ProviderError | None = None) -> None:
        self._value = value
        self._error = error

    async def get_value(self, owner_id: str, key: str) -> str | None:
        if self._error:
            raise self._error
        return self._value if key == "deletionProtection" else None


def both(fake: FakeReader, metadata: FakeMetadata | None = None) -> Drivers:
    """O mesmo fake atende aos dois drivers de leitura (usuário e autorização)."""
    return Drivers(users=fake, authorizations=fake, metadata=metadata or FakeMetadata())


def active(*, password: bool = True, verified: bool = True) -> IdentityUser:
    return IdentityUser("USER_STATE_ACTIVE", verified, password)


async def test_absent_user() -> None:
    result = await observe(both(FakeReader(None)), "u-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_present_reports_the_permissions_the_user_has_sorted() -> None:
    result = await observe(both(FakeReader(active(), set(PERMISSIONS))), "u-1")
    assert result.presence == "present"
    assert result.data == {
        "emailVerified": True,
        "userState": "active",
        "permissions": ["ipm.organization.get", "ipm.user.create", "ipm.user.get"],
        "deletionProtection": True,
    }


async def test_a_user_without_permissions_has_an_empty_list() -> None:
    result = await observe(both(FakeReader(active(), set())), "u-1")
    assert result.data["permissions"] == []


async def test_extra_permissions_are_reported_as_they_are() -> None:
    result = await observe(both(FakeReader(active(), PERMISSIONS | {"ipm.user.admin"})), "u-1")
    assert "ipm.user.admin" in result.data["permissions"]


async def test_unactivated_user_is_initial() -> None:
    result = await observe(
        both(FakeReader(active(password=False, verified=False), set())),
        "u-1",
    )
    assert result.data["userState"] == "initial"
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
    assert user_state(IdentityUser("USER_STATE_INACTIVE", True, True)) == "inactive"
    assert user_state(IdentityUser("USER_STATE_LOCKED", True, True)) == "locked"
    assert user_state(IdentityUser("USER_STATE_ACTIVE", True, False)) == "initial"
    assert user_state(IdentityUser("USER_STATE_DELETED", True, True)) == "inactive"


def test_log_identifiers_of_the_observation() -> None:
    assert log_identifiers("u-1") == {}  # a observação não conhece a Organization do usuário
