"""Ações do Executor: só a organização, idempotência, conflitos e `platformAccess` como estado."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from ipm_organization.executor.actions.organization_actions import Drivers, execute
from ipm_organization.executor.domain.errors import ActionFailedError
from ipm_organization.executor.domain.identity import IdentityOrganization, ProviderError

DESIRED = {"lifecycle": "present", "name": "acme", "platformAccess": "granted"}


@dataclass
class FakeOrganizationDriver:
    organizations: dict[str, IdentityOrganization] = field(default_factory=lambda: {})
    taken_names: set[str] = field(default_factory=lambda: set())
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get_organization(self, organization_id: str) -> IdentityOrganization | None:
        self._maybe_fail("get_organization")
        return self.organizations.get(organization_id)

    async def create_organization(self, organization_id: str, *, name: str) -> bool:
        self._maybe_fail("create_organization")
        self.calls.append(("create_organization", organization_id, name))
        if organization_id in self.organizations or name in self.taken_names:
            return False
        self.organizations[organization_id] = IdentityOrganization(name, active=True)
        self.taken_names.add(name)
        return True

    async def rename_organization(self, organization_id: str, *, name: str) -> None:
        self.calls.append(("rename_organization", organization_id, name))
        self.organizations[organization_id] = IdentityOrganization(
            name, self.organizations[organization_id].active
        )

    async def activate_organization(self, organization_id: str) -> None:
        self.calls.append(("activate_organization", organization_id))
        self.organizations[organization_id] = IdentityOrganization(
            self.organizations[organization_id].name, active=True
        )

    async def deactivate_organization(self, organization_id: str) -> None:
        self.calls.append(("deactivate_organization", organization_id))
        self.organizations[organization_id] = IdentityOrganization(
            self.organizations[organization_id].name, active=False
        )

    async def delete_organization(self, organization_id: str) -> None:
        self.calls.append(("delete_organization", organization_id))
        self.organizations.pop(organization_id, None)


@dataclass
class FakeMetadata:
    values: dict[tuple[str, str], str] = field(default_factory=lambda: {})

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        self.values[(owner_id, key)] = value


@dataclass
class FakeUserAccess:
    """Grant e papéis em memória; `writes` registra cada escrita, na ordem."""

    grant: list[str] | None = None
    administrators: dict[tuple[str, str], frozenset[str]] = field(default_factory=lambda: {})
    writes: list[tuple[str, ...]] = field(default_factory=lambda: [])
    grant_created_elsewhere: bool = False

    def organization_resource(self, organization_id: str) -> dict[str, Any]:
        return {"organizationId": organization_id}

    def grant_resource(self, organization_id: str) -> dict[str, Any]:
        return {"projectGrant": {"projectId": "roles-ipm", "organizationId": organization_id}}

    @staticmethod
    def _scope(resource: dict[str, Any]) -> str:
        return "grant" if "projectGrant" in resource else "organization"

    async def grant_permissions(self, organization_id: str) -> list[str] | None:
        return None if self.grant is None else sorted(self.grant)

    async def create_grant(self, organization_id: str, permissions: list[str]) -> bool:
        if self.grant_created_elsewhere:
            self.grant = ["ipm.user.get"]
            return False  # 409: outra tentativa criou antes
        self.writes.append(("create_grant", *permissions))
        self.grant = list(permissions)
        return True

    async def update_grant(self, organization_id: str, permissions: list[str]) -> None:
        self.writes.append(("update_grant", *permissions))
        self.grant = list(permissions)

    async def administrator_permissions(
        self, account_id: str, resource: dict[str, Any]
    ) -> frozenset[str] | None:
        return self.administrators.get((account_id, self._scope(resource)))

    async def create_administrator(
        self, account_id: str, resource: dict[str, Any], permissions: list[str]
    ) -> bool:
        key = (account_id, self._scope(resource))
        if key in self.administrators:
            return False
        self.writes.append(
            ("create_administrator", account_id, self._scope(resource), *permissions)
        )
        self.administrators[key] = frozenset(permissions)
        return True

    async def update_administrator(
        self, account_id: str, resource: dict[str, Any], permissions: list[str]
    ) -> None:
        self.writes.append(
            ("update_administrator", account_id, self._scope(resource), *permissions)
        )
        self.administrators[(account_id, self._scope(resource))] = frozenset(permissions)


def drivers(
    writer: FakeOrganizationDriver,
    metadata: FakeMetadata | None = None,
    user_access: FakeUserAccess | None = None,
) -> Drivers:
    return Drivers(
        organizations=writer,
        metadata=metadata or FakeMetadata(),
        user_access=user_access or FakeUserAccess(),
    )


async def test_create_makes_an_active_organization_with_the_resource_id() -> None:
    writer = FakeOrganizationDriver()

    await execute("create", "o-1", DESIRED, drivers(writer))

    assert writer.calls == [("create_organization", "o-1", "acme")]
    assert writer.organizations["o-1"] == IdentityOrganization("acme", active=True)


async def test_create_is_idempotent_when_the_organization_already_has_the_expected_name() -> None:
    writer = FakeOrganizationDriver(
        organizations={"o-1": IdentityOrganization("acme", active=True)}
    )

    await execute("create", "o-1", DESIRED, drivers(writer))

    assert [call[0] for call in writer.calls] == ["create_organization"]  # nada além da tentativa


async def test_create_with_a_name_used_by_another_organization_is_rejected() -> None:
    writer = FakeOrganizationDriver(taken_names={"acme"})

    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "o-1", DESIRED, drivers(writer))

    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)


async def test_create_with_an_id_used_by_another_name_is_rejected() -> None:
    writer = FakeOrganizationDriver(
        organizations={"o-1": IdentityOrganization("outra", active=True)}
    )

    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "o-1", DESIRED, drivers(writer))

    assert raised.value.reason == "Rejected" and not raised.value.retryable


async def test_create_with_revoked_access_deactivates_the_new_organization() -> None:
    writer = FakeOrganizationDriver()

    await execute("create", "o-1", {**DESIRED, "platformAccess": "revoked"}, drivers(writer))

    assert writer.calls[-1] == ("deactivate_organization", "o-1")
    assert writer.organizations["o-1"].active is False


async def test_create_without_a_name_is_rejected_before_calling_the_provider() -> None:
    writer = FakeOrganizationDriver()

    with pytest.raises(ActionFailedError):
        await execute("create", "o-1", {"lifecycle": "present"}, drivers(writer))

    assert writer.calls == []


async def test_update_renames_only_when_the_name_differs() -> None:
    writer = FakeOrganizationDriver(
        organizations={"o-1": IdentityOrganization("antigo", active=True)}
    )

    await execute("update", "o-1", {**DESIRED, "name": "novo"}, drivers(writer))
    assert writer.calls == [("rename_organization", "o-1", "novo")]

    writer.calls.clear()
    await execute("update", "o-1", {**DESIRED, "name": "novo"}, drivers(writer))
    assert writer.calls == []  # repetir não faz nada


async def test_update_follows_platform_access_by_activating_or_deactivating() -> None:
    writer = FakeOrganizationDriver(
        organizations={"o-1": IdentityOrganization("acme", active=True)}
    )

    await execute("update", "o-1", {**DESIRED, "platformAccess": "revoked"}, drivers(writer))
    assert writer.calls == [("deactivate_organization", "o-1")]

    writer.calls.clear()
    await execute("update", "o-1", {**DESIRED, "platformAccess": "granted"}, drivers(writer))
    assert writer.calls == [("activate_organization", "o-1")]

    writer.calls.clear()
    await execute("update", "o-1", DESIRED, drivers(writer))
    assert writer.calls == []  # já ativa: nada a fazer


async def test_update_of_a_missing_organization_is_a_permanent_failure() -> None:
    with pytest.raises(ActionFailedError) as raised:
        await execute("update", "o-1", DESIRED, drivers(FakeOrganizationDriver()))
    assert raised.value.reason == "Rejected" and not raised.value.retryable


async def test_delete_removes_the_organization_and_missing_is_success() -> None:
    writer = FakeOrganizationDriver(
        organizations={"o-1": IdentityOrganization("acme", active=True)}
    )

    await execute("delete", "o-1", {"lifecycle": "absent"}, drivers(writer))
    await execute("delete", "o-1", {"lifecycle": "absent"}, drivers(writer))

    assert writer.organizations == {}
    assert [call[0] for call in writer.calls] == ["delete_organization"] * 2


async def test_an_unsupported_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("reconcile", "o-1", DESIRED, drivers(FakeOrganizationDriver()))


async def test_provider_failures_propagate_to_the_engine() -> None:
    with pytest.raises(ProviderError):
        await execute(
            "create", "o-1", DESIRED, drivers(FakeOrganizationDriver(fail_on="create_organization"))
        )


async def test_create_and_update_write_the_deletion_protection_as_metadata() -> None:
    """A proteção é campo gerenciado: vai para o metadado da organização (decisão 0074)."""
    writer, metadata = FakeOrganizationDriver(), FakeMetadata()
    await execute("create", "o-1", DESIRED, drivers(writer, metadata))
    assert metadata.values == {("o-1", "deletionProtection"): "true"}

    unprotected = {**DESIRED, "deletionProtection": False}
    await execute("update", "o-1", unprotected, drivers(writer, metadata))
    assert metadata.values == {("o-1", "deletionProtection"): "false"}


async def test_delete_does_not_write_metadata() -> None:
    writer = FakeOrganizationDriver(
        organizations={"o-1": IdentityOrganization("acme", active=True)}
    )
    metadata = FakeMetadata()
    await execute("delete", "o-1", {"lifecycle": "absent"}, drivers(writer, metadata))
    assert metadata.values == {}


# ------------------------------------------------------------- preparo para os usuários (0081)

CATALOG = ["ipm.organization.get", "ipm.user.create", "ipm.user.get"]
USER_ACCESS = {
    "grantPermissions": CATALOG,
    "userExecutorAccountId": "user-executor",
    "userObserverAccountId": "user-observer",
}


def prepared(**overrides: Any) -> dict[str, Any]:
    return {"name": "acme", "platformAccess": "granted", "userAccess": USER_ACCESS, **overrides}


async def test_create_prepares_the_grant_before_the_roles_of_the_user_accounts() -> None:
    access = FakeUserAccess()
    await execute("create", "org-1", prepared(), drivers(FakeOrganizationDriver(), None, access))
    assert access.writes == [
        ("create_grant", *CATALOG),
        ("create_administrator", "user-executor", "organization", "ORG_USER_CREATOR"),
        ("create_administrator", "user-executor", "grant", "PROJECT_GRANT_OWNER"),
        ("create_administrator", "user-observer", "organization", "ORG_OWNER_VIEWER"),
    ]


async def test_a_prepared_organization_is_not_written_again() -> None:
    access = FakeUserAccess(
        grant=list(reversed(CATALOG)),
        administrators={
            ("user-executor", "organization"): frozenset({"ORG_USER_CREATOR"}),
            ("user-executor", "grant"): frozenset({"PROJECT_GRANT_OWNER"}),
            ("user-observer", "organization"): frozenset({"ORG_OWNER_VIEWER", "ORG_OWNER"}),
        },
    )
    writer = FakeOrganizationDriver()
    writer.organizations["org-1"] = IdentityOrganization("acme", active=True)
    await execute("update", "org-1", prepared(), drivers(writer, None, access))
    assert access.writes == []


async def test_a_different_grant_gets_exactly_the_catalog() -> None:
    access = FakeUserAccess(grant=["ipm.organization.get", "ipm.organization.delete"])
    writer = FakeOrganizationDriver()
    writer.organizations["org-1"] = IdentityOrganization("acme", active=True)
    await execute("update", "org-1", prepared(), drivers(writer, None, access))
    assert access.writes[0] == ("update_grant", *CATALOG)


async def test_a_grant_created_by_another_attempt_is_updated() -> None:
    access = FakeUserAccess(grant_created_elsewhere=True)
    await execute("create", "org-1", prepared(), drivers(FakeOrganizationDriver(), None, access))
    assert access.writes[0] == ("update_grant", *CATALOG)
    assert access.grant == CATALOG


async def test_a_missing_role_is_added_without_dropping_the_others() -> None:
    """`UpdateAdministrator` substitui o conjunto: vai a união com o que a conta já tem."""
    access = FakeUserAccess(
        grant=CATALOG,
        administrators={
            ("user-executor", "organization"): frozenset({"ORG_USER_MANAGER"}),
            ("user-executor", "grant"): frozenset({"PROJECT_GRANT_OWNER"}),
            ("user-observer", "organization"): frozenset({"ORG_OWNER_VIEWER"}),
        },
    )
    writer = FakeOrganizationDriver()
    writer.organizations["org-1"] = IdentityOrganization("acme", active=True)
    await execute("update", "org-1", prepared(), drivers(writer, None, access))
    assert access.writes == [
        (
            "update_administrator",
            "user-executor",
            "organization",
            "ORG_USER_CREATOR",
            "ORG_USER_MANAGER",
        ),
    ]


@pytest.mark.parametrize(
    "desired",
    [
        prepared(platformAccess="revoked"),
        {"name": "acme", "platformAccess": "granted"},  # `desired` anterior à decisão 0081
    ],
)
async def test_without_access_or_without_user_access_nothing_is_prepared(
    desired: dict[str, Any],
) -> None:
    access = FakeUserAccess()
    await execute("create", "org-1", desired, drivers(FakeOrganizationDriver(), None, access))
    assert access.writes == []
