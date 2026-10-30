"""Driver de leitura e escrita das roles de projeto no Zitadel (API v2; decisões 0083 e 0096).

Opera sobre `zitadel.project.v2.ProjectService` (`ListProjects`, `ListProjectRoles`,
`AddProjectRole`, `UpdateProjectRole` e `RemoveProjectRole`) com a conta
`ipm-permission-controller`.
Cada Permission (`<módulo>.<tipo>.<ação>`) é uma role de `roles-<módulo>`; a `operate`
(e `vault.*`) fica em `roles-operator`. Qualquer falha de leitura vira `ProviderError`, que a
observação trata como `unknown`, nunca como `absent`.
"""

from dataclasses import dataclass
from typing import Any, cast

from ipm_permission.controller.drivers.identity import IdentityConnection, ProviderError

PROJECT_SERVICE = "/zitadel.project.v2.ProjectService"
OPERATOR_PROJECT_MODULE = "operator"


@dataclass(frozen=True, slots=True)
class IdentityProjectRole:
    """Role de projeto lida do Zitadel."""

    key: str
    display_name: str
    group: str


def role_target(permission_name: str) -> tuple[str, str]:
    """`(módulo do projeto, módulo da Permission)` da chave `<módulo>.<tipo>.<ação>`.

    A ação `operate` (assim como qualquer permissão do módulo `vault`) vive em `roles-operator`;
    as demais, em `roles-<módulo>`.
    """
    parts = permission_name.split(".")
    if len(parts) != 3 or not all(parts):
        raise ProviderError("Rejected", retryable=False, detail="invalid permission name")
    target = (
        OPERATOR_PROJECT_MODULE if (parts[2] == "operate" or parts[0] == "vault") else parts[0]
    )
    return target, parts[0]


class ProjectRoleDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection
        self._project_ids: dict[str, str] = {}

    async def project_id_for_module(self, module: str) -> str:
        cached = self._project_ids.get(module)
        if cached is not None:
            return cached
        project_name = f"roles-{module}"
        response = await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/ListProjects",
            {
                "filters": [
                    {
                        "projectNameFilter": {
                            "projectName": project_name,
                            "method": "TEXT_FILTER_METHOD_EQUALS",
                        }
                    }
                ]
            },
        )
        assert response is not None  # noqa: S101 (sem accept_not_found/accept_conflict)
        projects = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("projects") or []
        )
        for project in projects:
            if project.get("name") == project_name:
                # A listagem da API v2 traz o ID no campo `projectId`.
                project_id = str(project.get("projectId", ""))
                if project_id:
                    self._project_ids[module] = project_id
                    return project_id
        raise ProviderError("Rejected", retryable=False, detail=f"project {project_name} not found")

    async def get(self, permission_name: str) -> IdentityProjectRole | None:
        """A role da Permission em `roles-<módulo>` ou `roles-operator`; `None` se não existe."""
        target, _ = role_target(permission_name)
        project_id = await self.project_id_for_module(target)
        response = await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/ListProjectRoles",
            {
                "projectId": project_id,
                "filters": [
                    {
                        "roleKeyFilter": {
                            "key": permission_name,
                            "method": "TEXT_FILTER_METHOD_EQUALS",
                        }
                    }
                ],
            },
        )
        assert response is not None  # noqa: S101 (sem accept_not_found/accept_conflict)
        roles = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("projectRoles") or []
        )
        for role in roles:
            key = str(role.get("key") or role.get("roleKey") or "")
            if key == permission_name:
                return IdentityProjectRole(
                    key=key,
                    display_name=str(role.get("displayName", "")),
                    group=str(role.get("group", "")),
                )
        return None

    async def add_or_update_role(
        self, permission_name: str, *, display_name: str, group: str
    ) -> None:
        """Cria a role; se ela já existe (409), atualiza descrição e grupo."""
        target, _ = role_target(permission_name)
        project_id = await self.project_id_for_module(target)
        created = await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/AddProjectRole",
            {
                "projectId": project_id,
                "roleKey": permission_name,
                "displayName": display_name,
                "group": group,
            },
            accept_conflict=True,
        )
        if created is None:
            await self.update_role(permission_name, display_name=display_name, group=group)

    async def update_role(self, permission_name: str, *, display_name: str, group: str) -> None:
        target, _ = role_target(permission_name)
        project_id = await self.project_id_for_module(target)
        await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/UpdateProjectRole",
            {
                "projectId": project_id,
                "roleKey": permission_name,
                "displayName": display_name,
                "group": group,
            },
        )

    async def remove_role(self, permission_name: str) -> None:
        target, _ = role_target(permission_name)
        project_id = await self.project_id_for_module(target)
        await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/RemoveProjectRole",
            {"projectId": project_id, "roleKey": permission_name},
            accept_not_found=True,
        )
