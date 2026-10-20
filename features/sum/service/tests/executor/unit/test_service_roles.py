from dataclasses import dataclass, field
from typing import Any

import pytest

from sum_service.executor.actions.service_roles import disable, enable
from sum_service.executor.domain.identity import Grant, ProviderError

PROJECTS = {"ipm": "proj-ipm"}
ROLES = ["ipm.organization.get", "ipm.organization.list"]


@dataclass
class FakeGranter:
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])

    def project_of(self, role: str) -> str:
        project = PROJECTS.get(role.split(".", 1)[0])
        if project is None:
            raise ProviderError("Rejected", retryable=False, detail="no roles project")
        return project

    async def grants(self, user_id: str) -> list[Grant]:
        return list(self.grants_by_user.get(user_id, []))

    async def create_grant(self, user_id: str, project_id: str, roles: list[str]) -> None:
        self.calls.append(("create", project_id, tuple(roles)))
        self.grants_by_user.setdefault(user_id, []).append(
            Grant(f"g-{project_id}", project_id, frozenset(roles))
        )

    async def update_grant(self, grant_id: str, roles: list[str]) -> None:
        self.calls.append(("update", grant_id, tuple(roles)))
        for user_grants in self.grants_by_user.values():
            for index, grant in enumerate(user_grants):
                if grant.grant_id == grant_id:
                    user_grants[index] = Grant(grant_id, grant.project_id, frozenset(roles))

    async def remove_grant(self, grant_id: str) -> None:
        self.calls.append(("remove", grant_id))
        for user_grants in self.grants_by_user.values():
            user_grants[:] = [grant for grant in user_grants if grant.grant_id != grant_id]


async def test_enable_creates_the_authorization_in_the_module_project() -> None:
    granter = FakeGranter()
    await enable(granter, "u-1", ROLES)
    assert granter.calls == [("create", "proj-ipm", tuple(sorted(ROLES)))]


async def test_enable_is_idempotent_and_keeps_the_roles_already_there() -> None:
    granter = FakeGranter(
        grants_by_user={"u-1": [Grant("g-1", "proj-ipm", frozenset([*ROLES, "ipm.x.extra"]))]}
    )
    await enable(granter, "u-1", ROLES)
    assert granter.calls == []  # já tem tudo: nenhuma chamada


async def test_enable_adds_only_the_missing_roles() -> None:
    granter = FakeGranter(grants_by_user={"u-1": [Grant("g-1", "proj-ipm", frozenset(ROLES[:1]))]})
    await enable(granter, "u-1", ROLES)
    assert granter.calls == [("update", "g-1", tuple(sorted(ROLES)))]


async def test_disable_removes_only_the_service_roles_and_keeps_the_others() -> None:
    granter = FakeGranter(
        grants_by_user={"u-1": [Grant("g-1", "proj-ipm", frozenset([*ROLES, "ipm.outro.x"]))]}
    )
    await disable(granter, "u-1", ROLES)
    assert granter.calls == [("update", "g-1", ("ipm.outro.x",))]


async def test_disable_removes_the_authorization_when_nothing_remains() -> None:
    granter = FakeGranter(grants_by_user={"u-1": [Grant("g-1", "proj-ipm", frozenset(ROLES))]})
    await disable(granter, "u-1", ROLES)
    assert granter.calls == [("remove", "g-1")]
    assert granter.grants_by_user["u-1"] == []


async def test_disable_of_a_user_without_the_roles_changes_nothing() -> None:
    granter = FakeGranter()
    await disable(granter, "u-1", ROLES)
    assert granter.calls == []


async def test_a_role_of_a_module_without_a_project_is_refused_before_any_call() -> None:
    granter = FakeGranter()
    with pytest.raises(ProviderError):
        await enable(granter, "u-1", ["core.account.get"])
    assert granter.calls == []
