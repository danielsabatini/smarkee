"""Ações do Executor: criação sem senha, idempotência, conflitos e autorização no projeto."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from core_account.executor.actions.account_actions import execute
from core_account.executor.domain.errors import ActionFailedError
from core_account.executor.domain.identity import Grant, ProviderError, ZitadelUser

ROLES = frozenset({"core.account.delete", "core.account.get", "sum.ipm.get"})
PROJECTS = {"core": "p-core", "sum": "p-sum"}
DESIRED = {
    "lifecycle": "present",
    "platformAccess": "granted",
    "platformRoles": sorted(ROLES),
    "givenName": "Ana",
    "familyName": "Souza",
    "email": "Ana@Example.com",
}


@dataclass
class FakeWriter:
    users: dict[str, ZitadelUser] = field(default_factory=lambda: {})
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    taken_emails: set[str] = field(default_factory=lambda: set())
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
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
        self.users[user_id] = ZitadelUser(email)
        self.taken_emails.add(email.lower())
        return True

    async def delete_user(self, user_id: str) -> None:
        self.calls.append(("delete_user", user_id))
        self.users.pop(user_id, None)

    async def grants(self, user_id: str) -> list[Grant]:
        self._maybe_fail("grants")
        return list(self.grants_by_user.get(user_id, []))

    def project_of(self, role: str) -> str:
        project = PROJECTS.get(role.split(".", 1)[0])
        if project is None:
            raise ProviderError("Rejected", retryable=False, detail="no roles project")
        return project

    async def create_grant(self, user_id: str, project_id: str, roles: list[str]) -> None:
        self.calls.append(("create_grant", project_id, sorted(roles)))
        self.grants_by_user.setdefault(user_id, []).append(
            Grant(f"g-{project_id}", project_id, frozenset(roles))
        )

    async def update_grant(self, user_id: str, grant_id: str, roles: list[str]) -> None:
        self.calls.append(("update_grant", grant_id, sorted(roles)))
        self.grants_by_user[user_id] = [
            Grant(g.grant_id, g.project_id, frozenset(roles)) if g.grant_id == grant_id else g
            for g in self.grants_by_user.get(user_id, [])
        ]

    async def remove_grant(self, user_id: str, grant_id: str) -> None:
        self.calls.append(("remove_grant", grant_id))
        self.grants_by_user[user_id] = [
            g for g in self.grants_by_user.get(user_id, []) if g.grant_id != grant_id
        ]


def names(writer: FakeWriter) -> list[str]:
    return [str(call[0]) for call in writer.calls]


async def test_create_makes_the_user_without_password_and_grants_roles() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, writer)
    assert names(writer) == ["create_user", "create_grant", "create_grant"]
    # Uma autorização por projeto: cada role vai para o projeto do seu módulo.
    assert ("create_grant", "p-core", ["core.account.delete", "core.account.get"]) in writer.calls
    assert ("create_grant", "p-sum", ["sum.ipm.get"]) in writer.calls


async def test_create_repeated_after_success_is_idempotent() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, writer)
    writer.users["u-1"] = ZitadelUser("Ana@Example.com")
    writer.calls.clear()

    await execute("create", "u-1", DESIRED, writer)

    assert names(writer) == ["create_user"]  # o usuário já tem senha e as roles


async def test_a_retry_before_activation_sends_no_second_email_and_keeps_the_grants() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, writer)
    writer.calls.clear()
    await execute("create", "u-1", DESIRED, writer)
    # O e-mail de verificação saiu na criação; repetir o `create` não manda outro.
    assert names(writer) == ["create_user"]  # a autorização já existe


async def test_a_retry_after_a_partial_failure_completes_the_missing_steps() -> None:
    writer = FakeWriter(fail_on="grants")
    with pytest.raises(ProviderError):
        await execute("create", "u-1", DESIRED, writer)
    assert "u-1" in writer.users  # o usuário já foi criado
    writer.fail_on = None
    await execute("create", "u-1", DESIRED, writer)
    assert {r for g in writer.grants_by_user["u-1"] for r in g.roles} == ROLES


async def test_email_in_use_by_another_user_is_a_permanent_rejection() -> None:
    writer = FakeWriter(taken_emails={"ana@example.com"})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, writer)
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert names(writer) == ["create_user"]  # recusado: nada é concedido


async def test_user_id_in_use_by_another_email_is_a_permanent_rejection() -> None:
    writer = FakeWriter(users={"u-1": ZitadelUser("outra@example.com")})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, writer)
    assert raised.value.retryable is False


@pytest.mark.parametrize("missing", ["givenName", "familyName", "email"])
async def test_create_without_the_user_data_is_rejected_and_calls_nothing(missing: str) -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != missing}
    with pytest.raises(ActionFailedError):
        await execute("create", "u-1", desired, writer)
    assert writer.calls == []


async def test_a_partial_grant_is_completed_keeping_the_extra_roles() -> None:
    writer = FakeWriter(
        users={"u-1": ZitadelUser("a@x.com")},
        grants_by_user={
            "u-1": [Grant("g-1", "p-core", frozenset({"core.account.get", "core.account.admin"}))]
        },
    )
    await execute("update", "u-1", DESIRED, writer)
    roles_by_project = {g.project_id: g.roles for g in writer.grants_by_user["u-1"]}
    assert roles_by_project["p-core"] == {
        "core.account.get",
        "core.account.delete",
        "core.account.admin",
    }
    assert roles_by_project["p-sum"] == {"sum.ipm.get"}
    assert names(writer) == ["update_grant", "create_grant"]


async def test_update_revoked_removes_the_grants() -> None:
    writer = FakeWriter(
        users={"u-1": ZitadelUser("a@x.com")},
        grants_by_user={
            "u-1": [
                Grant("g-1", "p-core", frozenset({"core.account.get"})),
                Grant("g-2", "p-sum", frozenset({"sum.ipm.get"})),
            ]
        },
    )
    await execute("update", "u-1", {**DESIRED, "platformAccess": "revoked"}, writer)
    assert names(writer) == ["remove_grant", "remove_grant"]


async def test_update_of_a_missing_user_is_a_permanent_rejection() -> None:
    with pytest.raises(ActionFailedError):
        await execute("update", "u-1", DESIRED, FakeWriter())


async def test_delete_is_idempotent() -> None:
    writer = FakeWriter(users={"u-1": ZitadelUser("a@x.com")})
    await execute("delete", "u-1", {"lifecycle": "absent"}, writer)
    await execute("delete", "u-1", {"lifecycle": "absent"}, writer)
    assert names(writer) == ["delete_user", "delete_user"]


async def test_an_unknown_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("noop", "u-1", DESIRED, FakeWriter())


async def test_create_without_platform_roles_is_rejected_without_touching_the_provider() -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != "platformRoles"}
    with pytest.raises(ActionFailedError) as error:
        await execute("create", "u-1", desired, writer)
    assert error.value.retryable is False
    assert writer.calls == []


async def test_roles_come_only_from_the_desired_platform_roles() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", {**DESIRED, "platformRoles": ["core.account.get"]}, writer)
    assert ("create_grant", "p-core", ["core.account.get"]) in writer.calls


async def test_a_role_of_a_module_without_a_roles_project_is_rejected_before_any_grant() -> None:
    """O Executor não concede roles de módulos fora de `project_ids` (decisão 0032)."""
    writer = FakeWriter()
    with pytest.raises(ProviderError) as raised:
        await execute(
            "create", "u-1", {**DESIRED, "platformRoles": ["ipm.organization.get"]}, writer
        )
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert "create_grant" not in names(writer)
