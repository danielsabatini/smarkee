"""Mapeamento do Zitadel para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

import json

from ipm_serviceaccount.observer.domain.identity import (
    IdentityKey,
    IdentityMachine,
    ProviderError,
)
from ipm_serviceaccount.observer.domain.observation import (
    Drivers,
    log_identifiers,
    observe,
    observed_keys,
)

PERMISSIONS = {"ipm.serviceaccount.get", "ipm.organization.get", "ipm.serviceaccount.create"}
FP_A, FP_B = "a" * 64, "b" * 64
EXPIRES = "2027-01-01T00:00:00Z"


class FakeReader:
    def __init__(
        self,
        machine: IdentityMachine | None,
        permissions: set[str] | None = None,
        keys: list[IdentityKey] | None = None,
        error: ProviderError | None = None,
        permissions_error: ProviderError | None = None,
    ) -> None:
        self._machine, self._permissions, self._keys = machine, permissions or set(), keys or []
        self._error, self._permissions_error = error, permissions_error

    async def get_machine(self, user_id: str) -> IdentityMachine | None:
        if self._error:
            raise self._error
        return self._machine

    async def list_keys(self, user_id: str) -> list[IdentityKey]:
        return self._keys

    async def granted_permissions(self, user_id: str) -> set[str]:
        if self._permissions_error:
            raise self._permissions_error
        return self._permissions


class FakeMetadata:
    def __init__(
        self,
        values: dict[str, str] | None = None,
        error: ProviderError | None = None,
    ) -> None:
        self._values = {"deletionProtection": "true"} if values is None else values
        self._error = error

    async def get_value(self, owner_id: str, key: str) -> str | None:
        if self._error:
            raise self._error
        return self._values.get(key)


def both(fake: FakeReader, metadata: FakeMetadata | None = None) -> Drivers:
    """O mesmo fake atende aos drivers de máquina e autorização."""
    return Drivers(machines=fake, authorizations=fake, metadata=metadata or FakeMetadata())


def active() -> IdentityMachine:
    return IdentityMachine("USER_STATE_ACTIVE", "ACCESS_TOKEN_TYPE_JWT")


async def test_absent_machine() -> None:
    result = await observe(both(FakeReader(None)), "u-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_present_reports_the_permissions_sorted_and_the_token_type() -> None:
    result = await observe(both(FakeReader(active(), set(PERMISSIONS))), "u-1")
    assert result.presence == "present"
    assert result.data == {
        "userState": "active",
        "accessTokenType": "jwt",
        "permissions": [
            "ipm.organization.get",
            "ipm.serviceaccount.create",
            "ipm.serviceaccount.get",
        ],
        "keys": [],
        "deletionProtection": True,
    }


async def test_a_machine_without_permissions_has_an_empty_list() -> None:
    result = await observe(both(FakeReader(active(), set())), "u-1")
    assert result.data["permissions"] == []


async def test_extra_permissions_are_reported_as_they_are() -> None:
    result = await observe(
        both(FakeReader(active(), PERMISSIONS | {"ipm.serviceaccount.admin"})), "u-1"
    )
    assert "ipm.serviceaccount.admin" in result.data["permissions"]


async def test_an_opaque_token_type_is_reported_so_the_reconciler_can_see_it() -> None:
    machine = IdentityMachine("USER_STATE_ACTIVE", "ACCESS_TOKEN_TYPE_BEARER")
    result = await observe(both(FakeReader(machine)), "u-1")
    assert result.data["accessTokenType"] == "bearer"


async def test_read_failures_are_unknown() -> None:
    for reader in (
        both(FakeReader(None, error=ProviderError("HTTP 503"))),
        both(FakeReader(active(), permissions_error=ProviderError("HTTP 500"))),
    ):
        result = await observe(reader, "u-1")
        assert (result.presence, result.data) == ("unknown", {})


async def test_deletion_protection_comes_from_the_metadata() -> None:
    """O metadado `deletionProtection` vira o campo do `observed` (decisão 0074)."""
    reader = FakeReader(active(), set(PERMISSIONS))
    result = await observe(both(reader, FakeMetadata({"deletionProtection": "false"})), "u-1")
    assert result.data["deletionProtection"] is False
    for values in ({}, {"deletionProtection": "yes"}):
        result = await observe(both(reader, FakeMetadata(values)), "u-1")
        assert "deletionProtection" not in result.data


async def test_the_description_comes_from_the_metadata() -> None:
    metadata = FakeMetadata({"deletionProtection": "true", "description": "CI deploy"})
    result = await observe(both(FakeReader(active()), metadata), "u-1")
    assert result.data["description"] == "CI deploy"


async def test_keys_cross_the_stored_mapping_with_the_listed_keys() -> None:
    mapping = json.dumps({FP_A: "k1", FP_B: "k2"})
    metadata = FakeMetadata({"deletionProtection": "true", "keys": mapping})
    reader = FakeReader(active(), keys=[IdentityKey("k1", EXPIRES)])
    result = await observe(both(reader, metadata), "u-1")
    assert result.data["keys"] == [
        {"fingerprint": FP_A, "keyId": "k1", "status": "active", "expiresAt": EXPIRES},
        {"fingerprint": FP_B, "keyId": "k2", "status": "expired"},
    ]


async def test_a_metadata_read_failure_is_unknown() -> None:
    failing = FakeMetadata(error=ProviderError("HTTP 503"))
    result = await observe(both(FakeReader(active(), set(PERMISSIONS)), failing), "u-1")
    assert (result.presence, result.data) == ("unknown", {})


def test_an_invalid_or_missing_mapping_yields_no_keys() -> None:
    listed = [IdentityKey("k1", EXPIRES)]
    assert observed_keys(None, listed) == []
    assert observed_keys("não é json", listed) == []
    assert observed_keys("[]", listed) == []


def test_log_identifiers_of_the_observation() -> None:
    assert log_identifiers("u-1") == {}  # a observação não conhece a Organization da máquina
