"""Ações do Executor: usuário na organização, idempotência, conflitos e permissões exatas."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from ipm_user.executor.actions.user_actions import Drivers, execute
from ipm_user.executor.domain.errors import ActionFailedError
from ipm_user.executor.domain.identity import Authorization, IdentityUser, ProviderError

ORGANIZATION = "org-c"
DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "organizationId": ORGANIZATION,
    "permissions": ["ipm.user.get", "ipm.user.list"],
    "givenName": "Bia",
    "familyName": "Lima",
    "email": "bia.lima@example.com",
}


@dataclass
class FakeWriter:
    users: dict[str, IdentityUser] = field(default_factory=lambda: {})
    authorizations: dict[str, Authorization] = field(default_factory=lambda: {})
    taken_emails: set[str] = field(default_factory=lambda: set())
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get_user(self, user_id: str) -> IdentityUser | None:
        return self.users.get(user_id)

    async def create_user(
        self,
        user_id: str,
        *,
        organization_id: str,
        given_name: str,
        family_name: str,
        email: str,
    ) -> bool:
        self._maybe_fail("create_user")
        self.calls.append(("create_user", user_id, organization_id))
        if user_id in self.users or email.lower() in self.taken_emails:
            return False
        self.users[user_id] = IdentityUser(email, organization_id)
        self.taken_emails.add(email.lower())
        return True

    async def delete_user(self, user_id: str) -> None:
        self.calls.append(("delete_user", user_id))
        self.users.pop(user_id, None)

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


def both(fake: FakeWriter, metadata: FakeMetadata | None = None) -> Drivers:
    """O mesmo fake atende aos dois drivers (usuário e autorização); o metadado é à parte."""
    return Drivers(users=fake, authorizations=fake, metadata=metadata or FakeMetadata())


def names(writer: FakeWriter) -> list[str]:
    return [str(call[0]) for call in writer.calls]


async def test_create_makes_the_user_in_the_organization_and_grants_the_permissions() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, both(writer))
    assert writer.calls == [
        ("create_user", "u-1", ORGANIZATION),
        ("create", ORGANIZATION, ["ipm.user.get", "ipm.user.list"]),
    ]


async def test_create_without_permissions_makes_no_authorization() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", {**DESIRED, "permissions": []}, both(writer))
    assert names(writer) == ["create_user"]


async def test_create_repeated_after_success_is_idempotent() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, both(writer))
    writer.calls.clear()

    await execute("create", "u-1", DESIRED, both(writer))

    assert names(writer) == ["create_user"]  # já existe, com as permissões certas


async def test_a_retry_after_a_partial_failure_completes_the_missing_steps() -> None:
    writer = FakeWriter(fail_on="authorization")
    with pytest.raises(ProviderError):
        await execute("create", "u-1", DESIRED, both(writer))
    writer.fail_on = None
    writer.calls.clear()

    await execute("create", "u-1", DESIRED, both(writer))

    assert names(writer) == ["create_user", "create"]


async def test_email_in_use_by_another_user_is_a_permanent_rejection() -> None:
    writer = FakeWriter(taken_emails={"bia.lima@example.com"})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, both(writer))
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)


@pytest.mark.parametrize(
    "existing",
    [
        IdentityUser("outra@example.com", ORGANIZATION),
        IdentityUser("bia.lima@example.com", "org-outra"),
    ],
)
async def test_user_id_in_use_by_another_user_is_a_permanent_rejection(
    existing: IdentityUser,
) -> None:
    writer = FakeWriter(users={"u-1": existing})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, both(writer))
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert names(writer) == ["create_user"]


@pytest.mark.parametrize("missing", ["givenName", "familyName", "email", "organizationId"])
async def test_create_without_the_user_data_is_rejected_and_calls_nothing(missing: str) -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != missing}
    with pytest.raises(ActionFailedError):
        await execute("create", "u-1", desired, both(writer))
    assert writer.calls == []


async def test_create_without_permissions_field_is_rejected_without_touching_the_provider() -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != "permissions"}
    with pytest.raises(ActionFailedError):
        await execute("create", "u-1", desired, both(writer))
    assert writer.calls == []


async def test_update_sets_exactly_the_desired_permissions() -> None:
    writer = FakeWriter(
        users={"u-1": IdentityUser("bia.lima@example.com", ORGANIZATION)},
        authorizations={"u-1": Authorization("a-1", frozenset({"ipm.user.get", "ipm.user.bind"}))},
    )
    await execute("update", "u-1", DESIRED, both(writer))
    # A permissão que sobra no provedor é revogada: as permissões são as do `desired`, exatamente.
    assert writer.calls == [("update", "a-1", ["ipm.user.get", "ipm.user.list"])]


async def test_update_without_permissions_removes_the_authorization() -> None:
    writer = FakeWriter(
        users={"u-1": IdentityUser("bia.lima@example.com", ORGANIZATION)},
        authorizations={"u-1": Authorization("a-1", frozenset({"ipm.user.get"}))},
    )
    await execute("update", "u-1", {**DESIRED, "permissions": []}, both(writer))
    assert writer.calls == [("remove", "a-1")]


async def test_update_with_the_same_permissions_changes_nothing() -> None:
    writer = FakeWriter(
        users={"u-1": IdentityUser("bia.lima@example.com", ORGANIZATION)},
        authorizations={"u-1": Authorization("a-1", frozenset(DESIRED["permissions"]))},
    )
    await execute("update", "u-1", DESIRED, both(writer))
    assert writer.calls == []


async def test_update_of_a_missing_user_or_of_another_organization_is_rejected() -> None:
    for users in ({}, {"u-1": IdentityUser("bia.lima@example.com", "org-outra")}):
        writer = FakeWriter(users=users)
        with pytest.raises(ActionFailedError) as raised:
            await execute("update", "u-1", DESIRED, both(writer))
        assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
        assert writer.calls == []


async def test_delete_is_idempotent() -> None:
    writer = FakeWriter()
    await execute("delete", "u-1", {"lifecycle": "absent"}, both(writer))
    await execute("delete", "u-1", {"lifecycle": "absent"}, both(writer))
    assert names(writer) == ["delete_user", "delete_user"]


async def test_an_unknown_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("rename", "u-1", DESIRED, both(FakeWriter()))


async def test_create_and_update_write_the_deletion_protection_as_metadata() -> None:
    """Sem o campo, o usuário fica desprotegido (decisão 0077); com `true`, protegido."""
    writer, metadata = FakeWriter(), FakeMetadata()
    await execute("create", "u-1", DESIRED, both(writer, metadata))
    assert metadata.values[("u-1", "deletionProtection")] == "false"

    await execute("update", "u-1", {**DESIRED, "deletionProtection": True}, both(writer, metadata))
    assert metadata.values[("u-1", "deletionProtection")] == "true"

    assert metadata.values[("u-1", "groups")] == "[]"

    await execute("delete", "u-1", {"lifecycle": "absent"}, both(writer, metadata))
    assert len(metadata.values) == 2  # a remoção não grava metadado
