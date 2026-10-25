"""Ações do Executor: Role no estado, idempotência e rejeições (sem banco)."""

from collections.abc import Mapping
from typing import Any

import pytest

from ipm_role.executor.actions.role_actions import Drivers, execute
from ipm_role.executor.domain.errors import ActionFailedError
from ipm_role.executor.domain.identity import StoredRole
from ipm_role.executor.drivers.role import RoleDriver

DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "name": "ipm.userAdmin",
    "description": "Administração de usuários.",
    "permissions": ["ipm.user.bind", "ipm.user.get"],
    "deletionProtection": True,
}


class InMemoryStore:
    """Substitui `StateStoreConnection`: leitura, escrita e remoção por `resource_id`."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    async def read_record(self, resource_id: str) -> dict[str, Any] | None:
        record = self.records.get(resource_id)
        return None if record is None else {**record, "permissions": list(record["permissions"])}

    async def write_record(self, resource_id: str, record: Mapping[str, Any]) -> None:
        self.records[resource_id] = dict(record)

    async def delete_record(self, resource_id: str) -> None:
        self.records.pop(resource_id, None)


async def test_execute_create_update_and_delete_on_the_store() -> None:
    store = InMemoryStore()
    driver = RoleDriver(store)  # pyright: ignore[reportArgumentType]
    drivers = Drivers(roles=driver)

    await execute("create", "role-ipm-user-admin", DESIRED, drivers)
    stored = await driver.get_role("role-ipm-user-admin")
    assert stored == StoredRole(
        name="ipm.userAdmin",
        description="Administração de usuários.",
        permissions=["ipm.user.bind", "ipm.user.get"],
        deletion_protection=True,
    )

    with pytest.raises(ActionFailedError) as exc_info:
        await execute(
            "update",
            "role-ipm-user-admin",
            {**DESIRED, "name": "ipm.userViewer"},
            drivers,
        )
    assert exc_info.value.reason == "Rejected"

    await execute(
        "update",
        "role-ipm-user-admin",
        {**DESIRED, "deletionProtection": False},
        drivers,
    )
    await execute(
        "delete",
        "role-ipm-user-admin",
        {**DESIRED, "lifecycle": "absent", "deletionProtection": False},
        drivers,
    )
    assert await driver.get_role("role-ipm-user-admin") is None


async def test_execute_is_idempotent_for_repeated_create_and_delete() -> None:
    store = InMemoryStore()
    drivers = Drivers(roles=RoleDriver(store))  # pyright: ignore[reportArgumentType]

    await execute("create", "role-ipm-user-admin", DESIRED, drivers)
    await execute("create", "role-ipm-user-admin", DESIRED, drivers)
    await execute("delete", "role-ipm-user-admin", DESIRED, drivers)
    await execute("delete", "role-ipm-user-admin", DESIRED, drivers)
    assert store.records == {}
