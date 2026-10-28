"""Ações do Controller: enable/disable idempotentes, por projeto, sem tocar nas alheias."""

from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from sum_service.controller.drivers.authorization import Grant
from sum_service.controller.drivers.identity import ProviderError
from sum_service.controller.engine.actions import ActionFailedError, execute

PROJECTS = {"ipm": "p-ipm", "bsm": "p-bsm"}
WANTED = ["ipm.organization.create", "ipm.organization.get", "bsm.account.get"]
MANAGED = [*WANTED, "ipm.organization.delete"]
DESIRED = {
    "lifecycle": "present",
    "ownerAccountId": "u-1",
    "service": "ipm",
    "servicePermissions": WANTED,
    "managedPermissions": MANAGED,
}


@dataclass
class FakeAuthorizations:
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail_on: str | None = None

    async def grants(self, user_id: str) -> list[Grant]:
        if self.fail_on == "grants":
            raise ProviderError("ProviderUnavailable", retryable=True)
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


def held(fake: FakeAuthorizations, user_id: str = "u-1") -> dict[str, frozenset[str]]:
    return {grant.project_id: grant.permissions for grant in fake.grants_by_user.get(user_id, [])}


async def test_enable_grants_each_permission_in_the_project_of_its_module() -> None:
    fake = FakeAuthorizations()
    await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert sorted(fake.calls) == [
        ("create_grant", "p-bsm", ["bsm.account.get"]),
        ("create_grant", "p-ipm", ["ipm.organization.create", "ipm.organization.get"]),
    ]


async def test_enable_repeated_changes_nothing() -> None:
    fake = FakeAuthorizations()
    await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    fake.calls.clear()
    await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert fake.calls == []


async def test_enable_completes_a_partial_grant_keeping_the_foreign_permissions() -> None:
    fake = FakeAuthorizations(
        grants_by_user={
            "u-1": [Grant("g-1", "p-ipm", frozenset({"ipm.organization.get", "ipm.user.get"}))]
        }
    )
    await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert held(fake)["p-ipm"] == {
        "ipm.organization.get",
        "ipm.organization.create",
        "ipm.user.get",
    }
    assert held(fake)["p-bsm"] == {"bsm.account.get"}


async def test_enable_revokes_the_managed_permissions_no_longer_wanted() -> None:
    fake = FakeAuthorizations(
        grants_by_user={
            "u-1": [
                Grant(
                    "g-1",
                    "p-ipm",
                    frozenset({*WANTED[:2], "ipm.organization.delete", "ipm.user.get"}),
                ),
                Grant("g-2", "p-bsm", frozenset({"bsm.account.get"})),
            ]
        }
    )
    await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert held(fake)["p-ipm"] == {*WANTED[:2], "ipm.user.get"}  # a gerenciada sai, a alheia fica


async def test_disable_removes_only_the_managed_permissions() -> None:
    fake = FakeAuthorizations(
        grants_by_user={
            "u-1": [
                Grant("g-1", "p-ipm", frozenset({*WANTED[:2], "ipm.user.get"})),
                Grant("g-2", "p-bsm", frozenset({"bsm.account.get"})),
            ]
        }
    )
    await execute("disable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert fake.calls == [("update_grant", "g-1", ["ipm.user.get"]), ("remove_grant", "g-2")]


async def test_disable_repeated_changes_nothing() -> None:
    fake = FakeAuthorizations(
        grants_by_user={"u-1": [Grant("g-1", "p-ipm", frozenset({"ipm.organization.get"}))]}
    )
    await execute("disable", "u-1", DESIRED, authorizations=cast("Any", fake))
    fake.calls.clear()
    await execute("disable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert fake.calls == []


async def test_a_retry_after_a_partial_failure_completes_the_missing_steps() -> None:
    fake = FakeAuthorizations(fail_on="grants")
    with pytest.raises(ProviderError):
        await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    fake.fail_on = None
    await execute("enable", "u-1", DESIRED, authorizations=cast("Any", fake))
    assert {p for permissions in held(fake).values() for p in permissions} == set(WANTED)


async def test_an_unknown_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError) as raised:
        await execute("noop", "u-1", DESIRED, authorizations=cast("Any", FakeAuthorizations()))
    assert raised.value.retryable is False


async def test_a_permission_of_an_unconfigured_module_is_rejected_before_any_grant() -> None:
    """O Controller não concede permissões de módulos fora de `project_ids` (decisão 0032)."""
    fake = FakeAuthorizations()
    desired = {**DESIRED, "servicePermissions": ["sum.service.get"], "managedPermissions": None}
    with pytest.raises(ProviderError) as raised:
        await execute("enable", "u-1", desired, authorizations=cast("Any", fake))
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert fake.calls == []


async def test_without_service_permissions_enable_calls_nothing() -> None:
    fake = FakeAuthorizations()
    await execute(
        "enable",
        "u-1",
        {**DESIRED, "servicePermissions": [], "managedPermissions": []},
        authorizations=cast("Any", fake),
    )
    assert fake.calls == []
