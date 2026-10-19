"""Ações do Executor: só a organização, idempotência, conflitos e `platformAccess` como estado."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from ipm_organization.executor.actions.organization_actions import execute
from ipm_organization.executor.domain.errors import ActionFailedError
from ipm_organization.executor.domain.identity import IdentityOrganization, ProviderError

DESIRED = {"lifecycle": "present", "name": "acme", "platformAccess": "granted"}


@dataclass
class FakeWriter:
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


async def test_create_makes_an_active_organization_with_the_resource_id() -> None:
    writer = FakeWriter()

    await execute("create", "o-1", DESIRED, writer)

    assert writer.calls == [("create_organization", "o-1", "acme")]
    assert writer.organizations["o-1"] == IdentityOrganization("acme", active=True)


async def test_create_is_idempotent_when_the_organization_already_has_the_expected_name() -> None:
    writer = FakeWriter(organizations={"o-1": IdentityOrganization("acme", active=True)})

    await execute("create", "o-1", DESIRED, writer)

    assert [call[0] for call in writer.calls] == ["create_organization"]  # nada além da tentativa


async def test_create_with_a_name_used_by_another_organization_is_rejected() -> None:
    writer = FakeWriter(taken_names={"acme"})

    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "o-1", DESIRED, writer)

    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)


async def test_create_with_an_id_used_by_another_name_is_rejected() -> None:
    writer = FakeWriter(organizations={"o-1": IdentityOrganization("outra", active=True)})

    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "o-1", DESIRED, writer)

    assert raised.value.reason == "Rejected" and not raised.value.retryable


async def test_create_with_revoked_access_deactivates_the_new_organization() -> None:
    writer = FakeWriter()

    await execute("create", "o-1", {**DESIRED, "platformAccess": "revoked"}, writer)

    assert writer.calls[-1] == ("deactivate_organization", "o-1")
    assert writer.organizations["o-1"].active is False


async def test_create_without_a_name_is_rejected_before_calling_the_provider() -> None:
    writer = FakeWriter()

    with pytest.raises(ActionFailedError):
        await execute("create", "o-1", {"lifecycle": "present"}, writer)

    assert writer.calls == []


async def test_update_renames_only_when_the_name_differs() -> None:
    writer = FakeWriter(organizations={"o-1": IdentityOrganization("antigo", active=True)})

    await execute("update", "o-1", {**DESIRED, "name": "novo"}, writer)
    assert writer.calls == [("rename_organization", "o-1", "novo")]

    writer.calls.clear()
    await execute("update", "o-1", {**DESIRED, "name": "novo"}, writer)
    assert writer.calls == []  # repetir não faz nada


async def test_update_follows_platform_access_by_activating_or_deactivating() -> None:
    writer = FakeWriter(organizations={"o-1": IdentityOrganization("acme", active=True)})

    await execute("update", "o-1", {**DESIRED, "platformAccess": "revoked"}, writer)
    assert writer.calls == [("deactivate_organization", "o-1")]

    writer.calls.clear()
    await execute("update", "o-1", {**DESIRED, "platformAccess": "granted"}, writer)
    assert writer.calls == [("activate_organization", "o-1")]

    writer.calls.clear()
    await execute("update", "o-1", DESIRED, writer)
    assert writer.calls == []  # já ativa: nada a fazer


async def test_update_of_a_missing_organization_is_a_permanent_failure() -> None:
    with pytest.raises(ActionFailedError) as raised:
        await execute("update", "o-1", DESIRED, FakeWriter())
    assert raised.value.reason == "Rejected" and not raised.value.retryable


async def test_delete_removes_the_organization_and_missing_is_success() -> None:
    writer = FakeWriter(organizations={"o-1": IdentityOrganization("acme", active=True)})

    await execute("delete", "o-1", {"lifecycle": "absent"}, writer)
    await execute("delete", "o-1", {"lifecycle": "absent"}, writer)

    assert writer.organizations == {}
    assert [call[0] for call in writer.calls] == ["delete_organization"] * 2


async def test_an_unsupported_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("reconcile", "o-1", DESIRED, FakeWriter())


async def test_provider_failures_propagate_to_the_engine() -> None:
    with pytest.raises(ProviderError):
        await execute("create", "o-1", DESIRED, FakeWriter(fail_on="create_organization"))
