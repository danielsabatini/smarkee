"""Testes unitários das ações do Executor de `ipm.permission` (decisão 0083)."""

import pytest

from ipm_permission.executor.actions.permission_actions import Drivers, execute
from ipm_permission.executor.domain.errors import ActionFailedError


class FakeProjectRoles:
    def __init__(self) -> None:
        self.roles: dict[tuple[str, str], tuple[str, str]] = {}

    async def add_or_update_role(
        self, module: str, role_key: str, *, display_name: str, group: str
    ) -> None:
        self.roles[(module, role_key)] = (display_name, group)

    async def update_role(
        self, module: str, role_key: str, *, display_name: str, group: str
    ) -> None:
        self.roles[(module, role_key)] = (display_name, group)

    async def remove_role(self, module: str, role_key: str) -> None:
        self.roles.pop((module, role_key), None)


async def test_create_update_and_delete_permission_role_in_module_project() -> None:
    fake = FakeProjectRoles()
    drivers = Drivers(project_roles=fake)
    desired = {
        "name": "ipm.user.bind",
        "description": "Atribuir e alterar permissões.",
        "grantable": True,
    }
    await execute("create", "perm-ipm-user-bind", desired, drivers)
    assert fake.roles[("ipm", "ipm.user.bind")] == ("Atribuir e alterar permissões.", "ipm")

    await execute(
        "update",
        "perm-ipm-user-bind",
        {**desired, "description": "Descrição atualizada."},
        drivers,
    )
    assert fake.roles[("ipm", "ipm.user.bind")] == ("Descrição atualizada.", "ipm")

    await execute("delete", "perm-ipm-user-bind", desired, drivers)
    assert ("ipm", "ipm.user.bind") not in fake.roles


async def test_admin_permission_is_routed_to_operator_project_keeping_module_group() -> None:
    fake = FakeProjectRoles()
    drivers = Drivers(project_roles=fake)
    desired = {
        "name": "ipm.user.admin",
        "description": "Operador: qualquer usuário da Organization",
        "grantable": False,
    }
    await execute("create", "perm-ipm-user-admin", desired, drivers)
    assert fake.roles[("operator", "ipm.user.admin")] == (
        "Operador: qualquer usuário da Organization",
        "ipm",
    )

    await execute("delete", "perm-ipm-user-admin", desired, drivers)
    assert ("operator", "ipm.user.admin") not in fake.roles


async def test_execute_rejects_invalid_permission_name() -> None:
    fake = FakeProjectRoles()
    drivers = Drivers(project_roles=fake)
    with pytest.raises(ActionFailedError):
        await execute(
            "create",
            "perm-bad",
            {"name": "invalid", "description": "Inválida."},
            drivers,
        )
