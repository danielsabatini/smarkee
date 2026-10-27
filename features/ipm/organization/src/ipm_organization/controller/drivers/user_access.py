"""Driver de leitura e escrita do preparo para usuários no Zitadel (API v2, v4.19.4; decisão 0081).

O Project Grant do projeto de permissões do `ipm` para a organização e as permissões de
administração das contas do `ipm/user` na organização e no Grant. Reaproveita os endpoints
verificados do Executor e do Observer (decisão 0096). A conta de escrita (`IAM_ORG_MANAGER`, de
instância, decisão 0060) já tem `project.grant.write` e `org.member.write`.

Verificado contra o Zitadel de dev em 2026-10-21: criar de novo responde `409` (`already_exists`),
`UpdateProjectGrant` com as mesmas permissões responde `200`, e remover a organização leva o Grant
e as permissões junto. `UpdateProjectGrant` e `UpdateAdministrator` **substituem** o conjunto: quem
chama envia o conjunto inteiro.
"""

from collections.abc import Iterable
from typing import Any, cast

from ipm_organization.controller.drivers.identity import IdentityConnection

PROJECT_SERVICE = "/zitadel.project.v2.ProjectService"
PERMISSION_SERVICE = "/zitadel.internal_permission.v2.InternalPermissionService"


class UserAccessDriver:
    def __init__(self, connection: IdentityConnection, project_id: str) -> None:
        self._connection = connection
        self._project_id = project_id

    def organization_resource(self, organization_id: str) -> dict[str, Any]:
        return {"organizationId": organization_id}

    def grant_resource(self, organization_id: str) -> dict[str, Any]:
        return {"projectGrant": {"projectId": self._project_id, "organizationId": organization_id}}

    async def grant_permissions(self, organization_id: str) -> list[str] | None:
        """As permissões do Grant para a organização, ou `None` se o Grant não existe."""
        response = await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/ListProjectGrants",
            {
                "filters": [
                    {"inProjectIdsFilter": {"ids": [self._project_id]}},
                    {"grantedOrganizationIdFilter": {"id": organization_id}},
                ]
            },
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
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

    async def create_grant(self, organization_id: str, permissions: list[str]) -> bool:
        """Cria o Grant. `False` se ele já existe (repetição ou corrida)."""
        response = await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/CreateProjectGrant",
            {
                "projectId": self._project_id,
                "grantedOrganizationId": organization_id,
                "roleKeys": permissions,
            },
            accept_conflict=True,
        )
        return response is not None

    async def update_grant(self, organization_id: str, permissions: list[str]) -> None:
        """Deixa o Grant com exatamente `permissions` (uma retirada sai também dos usuários)."""
        await self._connection.call(
            "POST",
            f"{PROJECT_SERVICE}/UpdateProjectGrant",
            {
                "projectId": self._project_id,
                "grantedOrganizationId": organization_id,
                "roleKeys": permissions,
            },
        )

    async def administrator_permissions(
        self, account_id: str, resource: dict[str, Any]
    ) -> frozenset[str] | None:
        """As permissões da conta no recurso, ou `None` se ela não é administradora dele."""
        response = await self._connection.call(
            "POST",
            f"{PERMISSION_SERVICE}/ListAdministrators",
            {
                "filters": [
                    {"resource": resource},
                    {"inUserIdsFilter": {"ids": [account_id]}},
                ]
            },
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        found = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("administrators") or []
        )
        for administrator in found:
            user = cast("dict[str, Any]", administrator.get("user") or {})
            if user.get("id") == account_id:
                roles = cast("list[object]", administrator.get("roles") or [])
                return frozenset(str(role) for role in roles)
        return None

    async def create_administrator(
        self, account_id: str, resource: dict[str, Any], permissions: Iterable[str]
    ) -> bool:
        """Dá as permissões à conta no recurso. `False` se ela já é administradora dele."""
        response = await self._connection.call(
            "POST",
            f"{PERMISSION_SERVICE}/CreateAdministrator",
            {"userId": account_id, "resource": resource, "roles": list(permissions)},
            accept_conflict=True,
        )
        return response is not None

    async def update_administrator(
        self, account_id: str, resource: dict[str, Any], permissions: Iterable[str]
    ) -> None:
        """Deixa a conta com exatamente `permissions` no recurso."""
        await self._connection.call(
            "POST",
            f"{PERMISSION_SERVICE}/UpdateAdministrator",
            {"userId": account_id, "resource": resource, "roles": list(permissions)},
        )

    async def list_administrators(
        self, organization_id: str, *, with_grant: bool
    ) -> list[dict[str, Any]]:
        """Administradores na organização e, com `with_grant`, no Grant dela, por conta."""
        resources = [self.organization_resource(organization_id)]
        if with_grant:
            resources.append(self.grant_resource(organization_id))
        held: dict[str, set[str]] = {}
        for resource in resources:
            response = await self._connection.call(
                "POST",
                f"{PERMISSION_SERVICE}/ListAdministrators",
                {"filters": [{"resource": resource}]},
            )
            assert response is not None  # noqa: S101 (sem accept_not_found)
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
        return [
            {"accountId": account, "permissions": sorted(held[account])} for account in sorted(held)
        ]
