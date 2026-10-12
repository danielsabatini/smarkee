"""Ações do Executor: criação sem senha, idempotência, conflitos e autorização no projeto."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from core_user_executor.actions.user_actions import execute
from core_user_executor.domain.errors import ActionFailedError
from core_user_executor.domain.identity import Grant, ProviderError, ZitadelUser
from core_user_executor.settings import ZitadelSettings

SETTINGS = ZitadelSettings()
ROLES = frozenset(SETTINGS.granted_roles)
DESIRED = {
    "lifecycle": "present",
    "platformAccess": "granted",
    "givenName": "Ana",
    "familyName": "Souza",
    "email": "Ana@Example.com",
}


@dataclass
class FakeWriter:
    users: dict[str, ZitadelUser] = field(default_factory=lambda: {})
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    taken_emails: set[str] = field(default_factory=lambda: set())
    calls: list[tuple[str, Any]] = field(default_factory=lambda: [])
    fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get_user(self, user_id: str) -> ZitadelUser | None:
        return self.users.get(user_id)

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool:
        self._maybe_fail("create_user")
        self.calls.append(("create_user", user_id))
        if user_id in self.users or email.lower() in self.taken_emails:
            return False
        self.users[user_id] = ZitadelUser(email, password_set=False)
        self.taken_emails.add(email.lower())
        return True

    async def send_password_link(self, user_id: str) -> None:
        self._maybe_fail("send_password_link")
        self.calls.append(("send_password_link", user_id))

    async def delete_user(self, user_id: str) -> None:
        self.calls.append(("delete_user", user_id))
        self.users.pop(user_id, None)

    async def grants(self, user_id: str) -> list[Grant]:
        self._maybe_fail("grants")
        return list(self.grants_by_user.get(user_id, []))

    async def create_grant(self, user_id: str, roles: list[str]) -> None:
        self.calls.append(("create_grant", sorted(roles)))
        self.grants_by_user[user_id] = [Grant("g-new", frozenset(roles))]

    async def update_grant(self, user_id: str, grant_id: str, roles: list[str]) -> None:
        self.calls.append(("update_grant", sorted(roles)))
        self.grants_by_user[user_id] = [Grant(grant_id, frozenset(roles))]

    async def remove_grant(self, user_id: str, grant_id: str) -> None:
        self.calls.append(("remove_grant", grant_id))
        self.grants_by_user[user_id] = []


def names(writer: FakeWriter) -> list[str]:
    return [name for name, _ in writer.calls]


async def test_create_makes_the_user_without_password_sends_the_link_and_grants_roles() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, writer, SETTINGS)
    assert names(writer) == ["create_user", "send_password_link", "create_grant"]
    assert ("create_grant", sorted(ROLES)) in writer.calls


async def test_create_repeated_after_success_is_idempotent_and_does_not_resend_the_link() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, writer, SETTINGS)
    writer.users["u-1"] = ZitadelUser("Ana@Example.com", password_set=True)
    writer.calls.clear()

    await execute("create", "u-1", DESIRED, writer, SETTINGS)

    assert names(writer) == ["create_user"]  # o usuário já tem senha e as roles


async def test_a_retry_before_the_password_is_set_resends_the_link() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, writer, SETTINGS)
    writer.calls.clear()
    await execute("create", "u-1", DESIRED, writer, SETTINGS)
    assert "send_password_link" in names(writer)
    assert "create_grant" not in names(writer)  # a autorização já existe


async def test_a_retry_after_a_partial_failure_completes_the_missing_steps() -> None:
    writer = FakeWriter(fail_on="grants")
    with pytest.raises(ProviderError):
        await execute("create", "u-1", DESIRED, writer, SETTINGS)
    assert "u-1" in writer.users  # o usuário já foi criado
    writer.fail_on = None
    await execute("create", "u-1", DESIRED, writer, SETTINGS)
    assert writer.grants_by_user["u-1"][0].roles == ROLES


async def test_email_in_use_by_another_user_is_a_permanent_rejection() -> None:
    writer = FakeWriter(taken_emails={"ana@example.com"})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, writer, SETTINGS)
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert "send_password_link" not in names(writer)


async def test_user_id_in_use_by_another_email_is_a_permanent_rejection() -> None:
    writer = FakeWriter(users={"u-1": ZitadelUser("outra@example.com", password_set=True)})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, writer, SETTINGS)
    assert raised.value.retryable is False


@pytest.mark.parametrize("missing", ["givenName", "familyName", "email"])
async def test_create_without_the_user_data_is_rejected_and_calls_nothing(missing: str) -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != missing}
    with pytest.raises(ActionFailedError):
        await execute("create", "u-1", desired, writer, SETTINGS)
    assert writer.calls == []


async def test_a_partial_grant_is_completed_keeping_the_extra_roles() -> None:
    writer = FakeWriter(
        users={"u-1": ZitadelUser("a@x.com", password_set=True)},
        grants_by_user={"u-1": [Grant("g-1", frozenset({"user.get", "platform.admin"}))]},
    )
    await execute("update", "u-1", DESIRED, writer, SETTINGS)
    assert writer.grants_by_user["u-1"][0].roles == ROLES | {"platform.admin"}
    assert names(writer) == ["update_grant"]


async def test_update_revoked_removes_the_grants() -> None:
    writer = FakeWriter(
        users={"u-1": ZitadelUser("a@x.com", password_set=True)},
        grants_by_user={"u-1": [Grant("g-1", ROLES)]},
    )
    await execute("update", "u-1", {**DESIRED, "platformAccess": "revoked"}, writer, SETTINGS)
    assert names(writer) == ["remove_grant"]


async def test_update_of_a_missing_user_is_a_permanent_rejection() -> None:
    with pytest.raises(ActionFailedError):
        await execute("update", "u-1", DESIRED, FakeWriter(), SETTINGS)


async def test_delete_is_idempotent() -> None:
    writer = FakeWriter(users={"u-1": ZitadelUser("a@x.com", password_set=True)})
    await execute("delete", "u-1", {"lifecycle": "absent"}, writer, SETTINGS)
    await execute("delete", "u-1", {"lifecycle": "absent"}, writer, SETTINGS)
    assert names(writer) == ["delete_user", "delete_user"]


async def test_an_unknown_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("noop", "u-1", DESIRED, FakeWriter(), SETTINGS)
