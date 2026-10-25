"""Ações do Executor: Role local, idempotência e escrita atômica."""

from pathlib import Path
from typing import Any

import pytest

from ipm_role.executor.actions.role_actions import Drivers, execute
from ipm_role.executor.domain.errors import ActionFailedError
from ipm_role.executor.domain.identity import StoredRole
from ipm_role.executor.drivers.role import RoleDriver
from ipm_role.executor.provider.storage import StateStoreConnection
from ipm_role.executor.settings import StorageSettings

DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "name": "ipm.userAdmin",
    "description": "Administração de usuários.",
    "permissions": ["ipm.user.bind", "ipm.user.get"],
    "deletionProtection": True,
}


async def test_execute_create_update_and_delete_on_local_store(tmp_path: Path) -> None:
    connection = StateStoreConnection(StorageSettings(directory=str(tmp_path)))
    driver = RoleDriver(connection)
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
