"""Driver de leitura do preparo para os usuários no Zitadel (API v2, v4.19.4; decisão 0081).

Espelho do driver de escrita do Executor (`executor/drivers/user_access.py`): o Project Grant do
projeto de roles do `ipm` para a organização e os papéis de administração na organização e no
Grant. Só leitura, com a conta do Observer (`IAM_OWNER_VIEWER`). Qualquer falha vira
`ProviderError`, e o chamador a trata como `unknown`.
"""

from typing import Any, cast

from ipm_organization.observer.provider.identity import IdentityConnection

PROJECT_SERVICE = "/zitadel.project.v2.ProjectService"
PERMISSION_SERVICE = "/zitadel.internal_permission.v2.InternalPermissionService"


class UserAccessDriver:
    def __init__(self, connection: IdentityConnection, project_id: str) -> None:
        self._connection = connection
        self._project_id = project_id

    async def grant_roles(self, organization_id: str) -> list[str] | None:
        """As roles do Grant para a organização, ou `None` se o Grant não existe."""
        response = await self._connection.request(
            "POST",
            f"{PROJECT_SERVICE}/ListProjectGrants",
            {
                "filters": [
                    {"inProjectIdsFilter": {"ids": [self._project_id]}},
                    {"grantedOrganizationIdFilter": {"id": organization_id}},
                ]
            },
        )
        grants = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("projectGrants") or []
        )
        for grant in grants:
            if (
                grant.get("projectId") == self._project_id
                and grant.get("grantedOrganizationId") == organization_id
            ):
                roles = cast("list[object]", grant.get("grantedRoleKeys") or [])
                return sorted(str(role) for role in roles)
        return None

    async def administrators(
        self, organization_id: str, *, with_grant: bool
    ) -> dict[str, frozenset[str]]:
        """Conta → papéis de administração na organização e, com `with_grant`, no Grant dela."""
        resources: list[dict[str, Any]] = [{"organizationId": organization_id}]
        if with_grant:
            resources.append(
                {"projectGrant": {"projectId": self._project_id, "organizationId": organization_id}}
            )
        held: dict[str, set[str]] = {}
        for resource in resources:
            response = await self._connection.request(
                "POST",
                f"{PERMISSION_SERVICE}/ListAdministrators",
                {"filters": [{"resource": resource}]},
            )
            found = cast(
                "list[dict[str, Any]]",
                self._connection.json(response).get("administrators") or [],
            )
            for administrator in found:
                user = cast("dict[str, Any]", administrator.get("user") or {})
                account_id = str(user.get("id", ""))
                if account_id:
                    roles = cast("list[object]", administrator.get("roles") or [])
                    held.setdefault(account_id, set()).update(str(role) for role in roles)
        return {account: frozenset(roles) for account, roles in held.items()}
