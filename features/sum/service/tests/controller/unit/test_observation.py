"""Observação da ligação: a leitura que falha vira `unknown`, nunca `absent`."""

from typing import Any, cast

from sum_service.controller.drivers.authorization import Grant
from sum_service.controller.drivers.identity import ProviderError
from sum_service.controller.engine.observation import observe_service

MANAGED = {"ipm.organization.create", "ipm.organization.get"}


class FakeReader:
    """Atende aos drivers de usuário (existência) e de autorização (leitura)."""

    def __init__(
        self,
        *,
        exists: bool = True,
        permissions: set[str] | None = None,
        user_error: ProviderError | None = None,
        grants_error: ProviderError | None = None,
    ) -> None:
        self._exists, self._permissions = exists, permissions or set()
        self._user_error, self._grants_error = user_error, grants_error

    async def exists(self, user_id: str) -> bool:
        if self._user_error:
            raise self._user_error
        return self._exists

    async def grants(self, user_id: str) -> list[Grant]:
        if self._grants_error:
            raise self._grants_error
        return [Grant("g-1", "p-1", frozenset(self._permissions))] if self._permissions else []


async def observe(reader: FakeReader):
    return await observe_service(
        "u-1", MANAGED, users=cast("Any", reader), authorizations=cast("Any", reader)
    )


async def test_a_missing_user_is_absent_with_no_permissions() -> None:
    result = await observe(FakeReader(exists=False))
    assert (result.presence, result.data) == ("absent", {"servicePermissions": []})


async def test_the_permissions_are_limited_to_the_managed_ones() -> None:
    result = await observe(FakeReader(permissions={*MANAGED, "ipm.user.get", "bsm.account.get"}))
    assert result.presence == "present"
    assert result.data == {"servicePermissions": sorted(MANAGED)}


async def test_a_user_without_authorizations_is_present_with_no_permissions() -> None:
    result = await observe(FakeReader())
    assert (result.presence, result.data) == ("present", {"servicePermissions": []})


async def test_a_failure_reading_the_user_is_unknown_not_absent() -> None:
    result = await observe(FakeReader(user_error=ProviderError("ProviderUnavailable")))
    assert (result.presence, result.data) == ("unknown", {})


async def test_a_failure_reading_the_authorizations_is_unknown() -> None:
    result = await observe(FakeReader(grants_error=ProviderError("ProviderUnavailable")))
    assert (result.presence, result.data) == ("unknown", {})
