"""Driver de escrita de roles de projeto em `roles-<módulo>` no Zitadel (API v2; decisão 0083).

Opera sobre `zitadel.project.v2.ProjectService` (`ListProjects`, `AddProjectRole`,
`UpdateProjectRole` e `RemoveProjectRole`) usando a conta `ipm-permission-executor` (`PROJECT_OWNER`
em cada projeto `roles-<módulo>`).
"""

from typing import Any, cast

from ipm_permission.executor.domain.identity import ProviderError
from ipm_permission.executor.provider.identity import IdentityConnection

PROJECT_SERVICE = "/zitadel.project.v2.ProjectService"


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

    async def add_or_update_role(
        self, module: str, role_key: str, *, display_name: str, group: str
    ) -> None:
        project_id = await self.project_id_for_module(module)
        created = await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/AddProjectRole",
            {
                "projectId": project_id,
                "roleKey": role_key,
                "displayName": display_name,
                "group": group,
            },
            accept_conflict=True,
        )
        if created is None:
            await self.update_role(module, role_key, display_name=display_name, group=group)

    async def update_role(
        self, module: str, role_key: str, *, display_name: str, group: str
    ) -> None:
        project_id = await self.project_id_for_module(module)
        await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/UpdateProjectRole",
            {
                "projectId": project_id,
                "roleKey": role_key,
                "displayName": display_name,
                "group": group,
            },
        )

    async def remove_role(self, module: str, role_key: str) -> None:
        project_id = await self.project_id_for_module(module)
        await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/RemoveProjectRole",
            {
                "projectId": project_id,
                "roleKey": role_key,
            },
            accept_not_found=True,
        )
