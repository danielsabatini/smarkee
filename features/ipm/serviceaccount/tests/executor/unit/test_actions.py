"""Ações do Executor: máquina na organização, chaves públicas, idempotência e permissões exatas."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from ipm_serviceaccount.executor.actions.serviceaccount_actions import Drivers, execute
from ipm_serviceaccount.executor.domain.errors import ActionFailedError
from ipm_serviceaccount.executor.domain.identity import (
    Authorization,
    IdentityMachine,
    ProviderError,
)

ORGANIZATION = "org-c"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
FUTURE = "2027-01-01T00:00:00Z"
PAST = "2026-10-01T00:00:00Z"
KEY_A = {"publicKey": "PEM-A", "expiresAt": FUTURE, "fingerprint": "a" * 64}
KEY_B = {"publicKey": "PEM-B", "expiresAt": FUTURE, "fingerprint": "b" * 64}
DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "organizationId": ORGANIZATION,
    "name": "deploy-bot",
    "permissions": ["ipm.serviceaccount.get", "ipm.serviceaccount.list"],
    "keys": [KEY_A],
}


@dataclass
class FakeWriter:
    machines: dict[str, IdentityMachine] = field(default_factory=lambda: {})
    keys: dict[str, dict[str, str]] = field(default_factory=lambda: {})  # user -> keyId -> PEM
    authorizations: dict[str, Authorization] = field(default_factory=lambda: {})
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail_on: str | None = None
    counter: int = 0

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get_machine(self, user_id: str) -> IdentityMachine | None:
        return self.machines.get(user_id)

    async def create_machine(
        self, user_id: str, *, organization_id: str, username: str, name: str
    ) -> bool:
        self.calls.append(("create_machine", user_id, organization_id, username, name))
        if user_id in self.machines:
            return False
        self.machines[user_id] = IdentityMachine(organization_id, "ACCESS_TOKEN_TYPE_JWT")
        return True

    async def delete_machine(self, user_id: str) -> None:
        self.calls.append(("delete_machine", user_id))
        self.machines.pop(user_id, None)

    async def list_key_ids(self, user_id: str) -> set[str]:
        return set(self.keys.get(user_id, {}))

    async def add_key(self, user_id: str, *, public_key: str, expires_at: str) -> str:
        self._maybe_fail("add_key")
        self.counter += 1
        key_id = f"k{self.counter}"
        self.keys.setdefault(user_id, {})[key_id] = public_key
        self.calls.append(("add_key", public_key, expires_at))
        return key_id

    async def remove_key(self, user_id: str, key_id: str) -> None:
        self.calls.append(("remove_key", key_id))
        self.keys.get(user_id, {}).pop(key_id, None)

    async def authorization(self, user_id: str, organization_id: str) -> Authorization | None:
        self._maybe_fail("authorization")
        return self.authorizations.get(user_id)

    async def create(self, user_id: str, organization_id: str, permissions: list[str]) -> None:
        self.calls.append(("create", organization_id, sorted(permissions)))
        self.authorizations[user_id] = Authorization(f"a-{user_id}", frozenset(permissions))

    async def update(self, authorization_id: str, permissions: list[str]) -> None:
        self.calls.append(("update", authorization_id, sorted(permissions)))
        for user_id, current in self.authorizations.items():
            if current.authorization_id == authorization_id:
                self.authorizations[user_id] = Authorization(
                    authorization_id, frozenset(permissions)
                )

    async def remove(self, authorization_id: str) -> None:
        self.calls.append(("remove", authorization_id))
        self.authorizations = {
            user_id: current
            for user_id, current in self.authorizations.items()
            if current.authorization_id != authorization_id
        }


@dataclass
class FakeMetadata:
    values: dict[tuple[str, str], str] = field(default_factory=lambda: {})

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        self.values[(owner_id, key)] = value

    async def get_value(self, owner_id: str, key: str) -> str | None:
        return self.values.get((owner_id, key))


def both(fake: FakeWriter, metadata: FakeMetadata | None = None) -> Drivers:
    """O mesmo fake atende aos drivers de máquina e autorização; o metadado é à parte."""
    store = metadata or FakeMetadata()
    return Drivers(machines=fake, authorizations=fake, metadata=store, metadata_reader=store)


def names(writer: FakeWriter) -> list[str]:
    return [str(call[0]) for call in writer.calls]


async def run(
    operation: str, writer: FakeWriter, metadata: FakeMetadata, desired: dict[str, Any] = DESIRED
) -> None:
    await execute(operation, "u-1", desired, both(writer, metadata), NOW)


async def test_create_makes_the_machine_registers_the_public_key_and_grants_the_permissions() -> (
    None
):
    writer, metadata = FakeWriter(), FakeMetadata()
    await run("create", writer, metadata)
    assert writer.calls == [
        ("create_machine", "u-1", ORGANIZATION, "u-1", "deploy-bot"),
        ("create", ORGANIZATION, ["ipm.serviceaccount.get", "ipm.serviceaccount.list"]),
        ("add_key", "PEM-A", FUTURE),
    ]
    assert json.loads(metadata.values[("u-1", "keys")]) == {"a" * 64: "k1"}


async def test_create_without_permissions_makes_no_authorization() -> None:
    writer = FakeWriter()
    await run("create", writer, FakeMetadata(), {**DESIRED, "permissions": []})
    assert "create" not in names(writer)


async def test_create_repeated_after_success_is_idempotent() -> None:
    writer, metadata = FakeWriter(), FakeMetadata()
    await run("create", writer, metadata)
    writer.calls.clear()

    await run("create", writer, metadata)

    assert names(writer) == ["create_machine"]  # já existe, com chave e permissões certas


async def test_a_retry_after_a_partial_failure_completes_the_missing_steps() -> None:
    writer, metadata = FakeWriter(fail_on="add_key"), FakeMetadata()
    with pytest.raises(ProviderError):
        await run("create", writer, metadata)
    writer.fail_on = None
    writer.calls.clear()

    await run("create", writer, metadata)

    assert names(writer) == ["create_machine", "add_key"]


async def test_a_key_left_without_a_mapping_is_removed_before_the_new_one_is_added() -> None:
    """Falha entre `AddKey` e a gravação do mapa: a chave sobra no provedor e é limpa no retry."""
    writer = FakeWriter(
        machines={"u-1": IdentityMachine(ORGANIZATION, "ACCESS_TOKEN_TYPE_JWT")},
        keys={"u-1": {"orphan": "PEM-X"}},
    )
    await run("create", writer, FakeMetadata())
    assert ("remove_key", "orphan") in writer.calls
    assert set(writer.keys["u-1"].values()) == {"PEM-A"}


async def test_machine_id_in_use_by_another_organization_is_a_permanent_rejection() -> None:
    writer = FakeWriter(machines={"u-1": IdentityMachine("org-outra", "ACCESS_TOKEN_TYPE_JWT")})
    with pytest.raises(ActionFailedError) as raised:
        await run("create", writer, FakeMetadata())
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert names(writer) == ["create_machine"]


@pytest.mark.parametrize("missing", ["name", "organizationId", "permissions"])
async def test_create_without_the_required_data_is_rejected_and_calls_nothing(
    missing: str,
) -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != missing}
    with pytest.raises(ActionFailedError):
        await run("create", writer, FakeMetadata(), desired)
    assert writer.calls == []


async def test_update_sets_exactly_the_desired_permissions() -> None:
    writer = FakeWriter(
        machines={"u-1": IdentityMachine(ORGANIZATION, "ACCESS_TOKEN_TYPE_JWT")},
        authorizations={
            "u-1": Authorization(
                "a-1", frozenset({"ipm.serviceaccount.get", "ipm.serviceaccount.bind"})
            )
        },
    )
    await run("update", writer, FakeMetadata(), {**DESIRED, "keys": []})
    # A permissão que sobra no provedor é revogada: as permissões são as do `desired`, exatamente.
    assert writer.calls == [
        ("update", "a-1", ["ipm.serviceaccount.get", "ipm.serviceaccount.list"])
    ]


async def test_update_without_permissions_removes_the_authorization() -> None:
    writer = FakeWriter(
        machines={"u-1": IdentityMachine(ORGANIZATION, "ACCESS_TOKEN_TYPE_JWT")},
        authorizations={"u-1": Authorization("a-1", frozenset({"ipm.serviceaccount.get"}))},
    )
    await run("update", writer, FakeMetadata(), {**DESIRED, "permissions": [], "keys": []})
    assert writer.calls == [("remove", "a-1")]


async def test_update_of_a_missing_machine_or_of_another_organization_is_rejected() -> None:
    for machines in ({}, {"u-1": IdentityMachine("org-outra", "ACCESS_TOKEN_TYPE_JWT")}):
        writer = FakeWriter(machines=machines)
        with pytest.raises(ActionFailedError) as raised:
            await run("update", writer, FakeMetadata())
        assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
        assert writer.calls == []


async def test_rotation_adds_the_new_key_and_removes_the_old_one() -> None:
    writer, metadata = FakeWriter(), FakeMetadata()
    await run("create", writer, metadata)
    writer.calls.clear()

    await run("update", writer, metadata, {**DESIRED, "keys": [KEY_A, KEY_B]})
    assert names(writer) == ["add_key"]
    assert json.loads(metadata.values[("u-1", "keys")]) == {"a" * 64: "k1", "b" * 64: "k2"}
    writer.calls.clear()

    await run("update", writer, metadata, {**DESIRED, "keys": [KEY_B]})
    assert writer.calls == [("remove_key", "k1")]
    assert json.loads(metadata.values[("u-1", "keys")]) == {"b" * 64: "k2"}
    assert set(writer.keys["u-1"]) == {"k2"}


async def test_an_expired_desired_key_is_not_recreated() -> None:
    writer, metadata = FakeWriter(), FakeMetadata()
    expired = {**KEY_A, "expiresAt": PAST}
    await run("create", writer, metadata, {**DESIRED, "keys": [expired, KEY_B]})
    assert [call[1] for call in writer.calls if call[0] == "add_key"] == ["PEM-B"]


async def test_delete_is_idempotent() -> None:
    writer = FakeWriter()
    await run("delete", writer, FakeMetadata(), {"lifecycle": "absent"})
    await run("delete", writer, FakeMetadata(), {"lifecycle": "absent"})
    assert names(writer) == ["delete_machine", "delete_machine"]


async def test_an_unknown_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await run("rename", FakeWriter(), FakeMetadata())


async def test_create_and_update_write_protection_and_description_as_metadata() -> None:
    """Sem o campo, a service account fica protegida (decisão 0094); `false` desprotege."""
    writer, metadata = FakeWriter(), FakeMetadata()
    await run("create", writer, metadata)
    assert metadata.values[("u-1", "deletionProtection")] == "true"
    assert ("u-1", "description") not in metadata.values

    desired = {**DESIRED, "deletionProtection": False, "description": "CI deploy"}
    await run("update", writer, metadata, desired)
    assert metadata.values[("u-1", "deletionProtection")] == "false"
    assert metadata.values[("u-1", "description")] == "CI deploy"

    await run("delete", writer, metadata, {"lifecycle": "absent"})
    assert len(metadata.values) == 3  # a remoção não grava metadado (só: proteção, descrição, keys)
