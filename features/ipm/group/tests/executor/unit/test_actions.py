"""Ações do Executor: Grupo no estado, idempotência e rejeições (sem banco)."""

from collections.abc import Mapping
from typing import Any

import pytest

from ipm_group.executor.actions.group_actions import Drivers, execute
from ipm_group.executor.domain.errors import ActionFailedError
from ipm_group.executor.domain.identity import StoredGroup
from ipm_group.executor.drivers.group import GroupDriver

DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "organizationId": "org-1",
    "name": "auditors",
    "description": "Auditores da Organization.",
    "roles": ["ipm.userViewer", "core.accountViewer"],
    "deletionProtection": True,
}


class InMemoryStore:
    """Substitui `StateStoreConnection`: leitura, escrita e remoção por `resource_id`."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        record = self.records.get(resource_id)
        return None if record is None else {**record, "roles": list(record["roles"])}

    async def write_record(self, resource_id: str, record: Mapping[str, Any]) -> None:
        self.records[resource_id] = dict(record)

    async def delete_record(self, resource_id: str) -> None:
        self.records.pop(resource_id, None)


async def test_execute_create_update_and_delete_on_the_store() -> None:
    store = InMemoryStore()
    driver = GroupDriver(store)  # pyright: ignore[reportArgumentType]
    drivers = Drivers(groups=driver)

    await execute("create", "group-1", DESIRED, drivers)
    assert await driver.get_group("group-1") == StoredGroup(
        organization_id="org-1",
        name="auditors",
        description="Auditores da Organization.",
        roles=["core.accountViewer", "ipm.userViewer"],
        deletion_protection=True,
    )

    await execute("update", "group-1", {**DESIRED, "roles": ["ipm.userViewer"]}, drivers)
    stored = await driver.get_group("group-1")
    assert stored is not None
    assert stored.roles == ["ipm.userViewer"]

    await execute("delete", "group-1", {**DESIRED, "lifecycle": "absent"}, drivers)
    assert await driver.get_group("group-1") is None


async def test_name_and_organization_are_immutable() -> None:
    drivers = Drivers(groups=GroupDriver(InMemoryStore()))  # pyright: ignore[reportArgumentType]
    await execute("create", "group-1", DESIRED, drivers)

    for changed in ({"name": "others"}, {"organizationId": "org-2"}):
        with pytest.raises(ActionFailedError) as exc_info:
            await execute("update", "group-1", {**DESIRED, **changed}, drivers)
        assert exc_info.value.reason == "Rejected"
        with pytest.raises(ActionFailedError):
            await execute("create", "group-1", {**DESIRED, **changed}, drivers)


async def test_update_of_a_missing_group_and_invalid_desired_are_rejected() -> None:
    drivers = Drivers(groups=GroupDriver(InMemoryStore()))  # pyright: ignore[reportArgumentType]
    with pytest.raises(ActionFailedError) as missing:
        await execute("update", "group-1", DESIRED, drivers)
    assert missing.value.reason == "Rejected"
    for field in ("organizationId", "name", "description"):
        with pytest.raises(ActionFailedError):
            await execute("create", "group-1", {**DESIRED, field: ""}, drivers)
    with pytest.raises(ActionFailedError):
        await execute("archive", "group-1", DESIRED, drivers)


async def test_execute_is_idempotent_for_repeated_create_and_delete() -> None:
    store = InMemoryStore()
    drivers = Drivers(groups=GroupDriver(store))  # pyright: ignore[reportArgumentType]

    await execute("create", "group-1", DESIRED, drivers)
    await execute("create", "group-1", DESIRED, drivers)
    await execute("delete", "group-1", DESIRED, drivers)
    await execute("delete", "group-1", DESIRED, drivers)
    assert store.records == {}
