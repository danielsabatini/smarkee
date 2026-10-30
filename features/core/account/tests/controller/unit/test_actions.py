"""Ações do Controller: criação sem senha, idempotência, conflitos e autorização no projeto."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from core_account.controller.drivers.authorization import Grant
from core_account.controller.drivers.identity import ProviderError
from core_account.controller.drivers.user import IdentityUser
from core_account.controller.engine.actions import ActionFailedError, execute

PERMISSIONS = frozenset({"core.account.delete", "core.account.get", "sum.ipm.get"})
PROJECTS = {"core": "p-core", "sum": "p-sum"}
DESIRED = {
    "lifecycle": "present",
    "platformAccess": "granted",
    "platformPermissions": sorted(PERMISSIONS),
    "givenName": "Ana",
    "familyName": "Souza",
    "email": "Ana@Example.com",
}


@dataclass
class FakeWriter:
    users: dict[str, IdentityUser] = field(default_factory=lambda: {})
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    taken_emails: set[str] = field(default_factory=lambda: set())
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get_user(self, user_id: str) -> IdentityUser | None:
        return self.users.get(user_id)

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool:
        self._maybe_fail("create_user")
        self.calls.append(("create_user", user_id))
        if user_id in self.users or email.lower() in self.taken_emails:
            return False
        self.users[user_id] = user(email)
        self.taken_emails.add(email.lower())
        return True

    async def delete_user(self, user_id: str) -> None:
        self.calls.append(("delete_user", user_id))
        self.users.pop(user_id, None)

    async def resend_activation(self, user_id: str) -> bool:
        self.calls.append(("resend_activation", user_id))
        return True


    async def grants(self, user_id: str) -> list[Grant]:
        self._maybe_fail("grants")
        return list(self.grants_by_user.get(user_id, []))

    def project_of(self, permission: str) -> str:
        project = PROJECTS.get(permission.split(".", 1)[0])
        if project is None:
            raise ProviderError("Rejected", retryable=False, detail="no permissions project")
        return project

    async def create_grant(self, user_id: str, project_id: str, permissions: list[str]) -> None:
        self.calls.append(("create_grant", project_id, sorted(permissions)))
        self.grants_by_user.setdefault(user_id, []).append(
            Grant(f"g-{project_id}", project_id, frozenset(permissions))
        )

    async def update_grant(self, grant_id: str, permissions: list[str]) -> None:
        self.calls.append(("update_grant", grant_id, sorted(permissions)))
        for user_id, grants in self.grants_by_user.items():
            self.grants_by_user[user_id] = [
                Grant(g.grant_id, g.project_id, frozenset(permissions))
                if g.grant_id == grant_id
                else g
                for g in grants
            ]

    async def remove_grant(self, grant_id: str) -> None:
        self.calls.append(("remove_grant", grant_id))
        for user_id, grants in self.grants_by_user.items():
            self.grants_by_user[user_id] = [g for g in grants if g.grant_id != grant_id]


@dataclass
class FakeMetadata:
    values: dict[tuple[str, str], str] = field(default_factory=lambda: {})

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        self.values[(owner_id, key)] = value


def user(email: str, *, email_verified: bool = True) -> IdentityUser:
    return IdentityUser(
        email=email, state="USER_STATE_ACTIVE", email_verified=email_verified, password_set=True
    )


def both(fake: FakeWriter, metadata: FakeMetadata | None = None) -> dict[str, Any]:
    """O mesmo fake atende aos dois drivers (usuário e autorização); o metadado é à parte."""
    return {"users": fake, "authorizations": fake, "metadata": metadata or FakeMetadata()}


def names(writer: FakeWriter) -> list[str]:
    return [str(call[0]) for call in writer.calls]


async def test_create_makes_the_user_without_password_and_grants_permissions() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, **both(writer))
    assert names(writer) == ["create_user", "create_grant", "create_grant"]
    # Uma autorização por projeto: cada permissão vai para o projeto do seu módulo.
    assert ("create_grant", "p-core", ["core.account.delete", "core.account.get"]) in writer.calls
    assert ("create_grant", "p-sum", ["sum.ipm.get"]) in writer.calls


async def test_create_repeated_after_success_is_idempotent() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, **both(writer))
    writer.users["u-1"] = user("Ana@Example.com")
    writer.calls.clear()

    await execute("create", "u-1", DESIRED, **both(writer))

    assert names(writer) == ["create_user"]  # o usuário já tem senha e as permissões


async def test_a_retry_before_activation_sends_no_second_email_and_keeps_the_grants() -> None:
    writer = FakeWriter()
    await execute("create", "u-1", DESIRED, **both(writer))
    writer.calls.clear()
    await execute("create", "u-1", DESIRED, **both(writer))
    # O e-mail de verificação saiu na criação; repetir o `create` não manda outro.
    assert names(writer) == ["create_user"]  # a autorização já existe


async def test_a_retry_after_a_partial_failure_completes_the_missing_steps() -> None:
    writer = FakeWriter(fail_on="grants")
    with pytest.raises(ProviderError):
        await execute("create", "u-1", DESIRED, **both(writer))
    assert "u-1" in writer.users  # o usuário já foi criado
    writer.fail_on = None
    await execute("create", "u-1", DESIRED, **both(writer))
    assert {r for g in writer.grants_by_user["u-1"] for r in g.permissions} == PERMISSIONS


async def test_email_in_use_by_another_user_is_a_permanent_rejection() -> None:
    writer = FakeWriter(taken_emails={"ana@example.com"})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, **both(writer))
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert names(writer) == ["create_user"]  # recusado: nada é concedido


async def test_user_id_in_use_by_another_email_is_a_permanent_rejection() -> None:
    writer = FakeWriter(users={"u-1": user("outra@example.com")})
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "u-1", DESIRED, **both(writer))
    assert raised.value.retryable is False


@pytest.mark.parametrize("missing", ["givenName", "familyName", "email"])
async def test_create_without_the_user_data_is_rejected_and_calls_nothing(missing: str) -> None:
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != missing}
    with pytest.raises(ActionFailedError):
        await execute("create", "u-1", desired, **both(writer))
    assert writer.calls == []


async def test_a_partial_grant_is_completed_keeping_the_extra_permissions() -> None:
    writer = FakeWriter(
        users={"u-1": user("a@x.com")},
        grants_by_user={
            "u-1": [Grant("g-1", "p-core", frozenset({"core.account.get", "core.account.admin"}))]
        },
    )
    await execute("update", "u-1", DESIRED, **both(writer))
    permissions_by_project = {g.project_id: g.permissions for g in writer.grants_by_user["u-1"]}
    assert permissions_by_project["p-core"] == {
        "core.account.get",
        "core.account.delete",
        "core.account.admin",
    }
    assert permissions_by_project["p-sum"] == {"sum.ipm.get"}
    assert names(writer) == ["update_grant", "create_grant"]


async def test_update_revoked_removes_the_grants() -> None:
    writer = FakeWriter(
        users={"u-1": user("a@x.com")},
        grants_by_user={
            "u-1": [
                Grant("g-1", "p-core", frozenset({"core.account.get"})),
                Grant("g-2", "p-sum", frozenset({"sum.ipm.get"})),
            ]
        },
    )
    await execute("update", "u-1", {**DESIRED, "platformAccess": "revoked"}, **both(writer))
    assert names(writer) == ["remove_grant", "remove_grant"]


async def test_update_of_a_missing_user_is_a_permanent_rejection() -> None:
    with pytest.raises(ActionFailedError):
        await execute("update", "u-1", DESIRED, **both(FakeWriter()))


async def test_delete_is_idempotent() -> None:
    writer = FakeWriter(users={"u-1": user("a@x.com")})
    await execute("delete", "u-1", {"lifecycle": "absent"}, **both(writer))
    await execute("delete", "u-1", {"lifecycle": "absent"}, **both(writer))
    assert names(writer) == ["delete_user", "delete_user"]


async def test_update_resends_activation_if_requested_and_not_verified() -> None:
    writer = FakeWriter(users={"u-1": user("a@x.com", email_verified=False)})
    metadata = FakeMetadata()
    desired = {**DESIRED, "resendRequestedAt": "2026-10-30T15:00:00Z"}
    await execute("update", "u-1", desired, **both(writer, metadata=metadata))
    assert ("resend_activation", "u-1") in writer.calls
    assert metadata.values.get(("u-1", "lastResendAt")) == "2026-10-30T15:00:00Z"




async def test_an_unknown_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("noop", "u-1", DESIRED, **both(FakeWriter()))


async def test_create_without_platform_permissions_is_rejected_without_touching_the_provider() -> (
    None
):
    writer = FakeWriter()
    desired = {key: value for key, value in DESIRED.items() if key != "platformPermissions"}
    with pytest.raises(ActionFailedError) as error:
        await execute("create", "u-1", desired, **both(writer))
    assert error.value.retryable is False
    assert writer.calls == []


async def test_permissions_come_only_from_the_desired_platform_permissions() -> None:
    writer = FakeWriter()
    await execute(
        "create", "u-1", {**DESIRED, "platformPermissions": ["core.account.get"]}, **both(writer)
    )
    assert ("create_grant", "p-core", ["core.account.get"]) in writer.calls


async def test_a_permission_of_an_unconfigured_module_is_rejected_before_any_grant() -> None:
    """O Controller não concede permissões de módulos fora de `project_ids` (decisão 0032)."""
    writer = FakeWriter()
    with pytest.raises(ProviderError) as raised:
        await execute(
            "create",
            "u-1",
            {**DESIRED, "platformPermissions": ["ipm.organization.get"]},
            **both(writer),
        )
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert "create_grant" not in names(writer)


async def test_create_and_update_write_the_deletion_protection_as_metadata() -> None:
    """A proteção é campo gerenciado: vai para o metadado do usuário (decisão 0074)."""
    writer, metadata = FakeWriter(), FakeMetadata()
    await execute("create", "u-1", DESIRED, **both(writer, metadata))
    assert metadata.values == {("u-1", "deletionProtection"): "true"}

    unprotected = {**DESIRED, "deletionProtection": False}
    await execute("update", "u-1", unprotected, **both(writer, metadata))
    assert metadata.values == {("u-1", "deletionProtection"): "false"}
