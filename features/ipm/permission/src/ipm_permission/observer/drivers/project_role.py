"""Driver de leitura da role de projeto no Zitadel (API v2; decisão 0083).

Espelho do driver de escrita do Executor (`executor/drivers/project_role.py`): resolve o ID do
projeto `roles-<módulo>` via `ListProjects` (com cache em memória) e lê a role via
`ListProjectRoles`. Só leitura, com a conta `ipm-permission-observer` (`PROJECT_OWNER_VIEWER` nos
projetos `roles-<módulo>`). Qualquer falha vira `ProviderError`, tratada como `unknown`.
"""

from typing import Any, cast

from ipm_permission.observer.domain.identity import IdentityProjectRole, ProviderError
from ipm_permission.observer.provider.identity import IdentityConnection

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
        response = await self._connection.request(
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
        raise ProviderError(f"project {project_name} not found")

    async def get(self, permission_name: str) -> IdentityProjectRole | None:
        """A role correspondente a `permission_name` em `roles-<módulo>`, ou `None` se ausente."""
        module = permission_name.split(".", 1)[0]
        if not module:
            raise ProviderError("invalid permission name")
        project_id = await self.project_id_for_module(module)
        response = await self._connection.request(
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
