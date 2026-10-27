"""Driver de leitura e escrita do preparo da Organization para usuários (`userAccess`).

Gerencia o Project Grant do projeto `roles-ipm` e as permissões de administradores
das contas da plataforma na Organization (decisões 0081, 0094, 0096).
Todas as chamadas operam com menor privilégio passando `org_id=organization_id`.
"""

from collections.abc import Iterable
from typing import Any, cast

from ipm_organization.controller.drivers.identity import IdentityConnection

ORGANIZATION_TYPE = "ORGANIZATION_RESOURCE_TYPE_ORG"
PROJECT_GRANT_TYPE = "ORGANIZATION_RESOURCE_TYPE_PROJECT_GRANT"
ALREADY_EXISTS_ID = "EVENT-398fs"


class UserAccessDriver:
    def __init__(self, connection: IdentityConnection, project_id: str) -> None:
        self._connection = connection
        self._project_id = project_id

    def organization_resource(self, organization_id: str) -> dict[str, Any]:
        return {
            "resourceType": ORGANIZATION_TYPE,
            "org": {"orgId": organization_id},
        }

    def grant_resource(self, organization_id: str) -> dict[str, Any]:
        return {
            "resourceType": PROJECT_GRANT_TYPE,
            "projectGrant": {
                "orgId": organization_id,
                "projectId": self._project_id,
            },
        }

    async def grant_permissions(self, organization_id: str) -> list[str] | None:
        """Permissões do Project Grant do projeto roles-ipm; None se o Grant não existe."""
        response = await self._connection.call(
            "POST",
            "/v2/project_grants",
            {
                "queries": [
                    {"grantedOrgIdQuery": {"grantedOrgId": organization_id}},
                    {"projectIdQuery": {"projectId": self._project_id}},
                ]
            },
            org_id=organization_id,
        )
        assert response is not None  # noqa: S101
        grants = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        for grant in grants:
            if (
                grant.get("grantedOrgId") == organization_id
                and grant.get("projectId") == self._project_id
            ):
                roles = cast("list[object]", grant.get("roleKeys") or [])
                return sorted(str(role) for role in roles)
        return None

    async def create_grant(self, organization_id: str, permissions: list[str]) -> bool:
        """Cria o Project Grant. False se já existia (idempotência)."""
        response = await self._connection.call(
            "POST",
            f"/v2/projects/{self._project_id}/grants",
            {"grantedOrgId": organization_id, "roleKeys": permissions},
            accept_conflict=True,
            org_id=organization_id,
        )
        return response is not None

    async def update_grant(self, organization_id: str, permissions: list[str]) -> None:
        await self._connection.call(
            "PUT",
            f"/v2/projects/{self._project_id}/grants/{organization_id}",
            {"roleKeys": permissions},
            org_id=organization_id,
        )

    async def administrator_permissions(
        self, account_id: str, resource: dict[str, Any]
    ) -> frozenset[str] | None:
        """Permissões da conta no recurso; None se a conta não é administradora dele."""
        response = await self._connection.call(
            "POST",
            "/v2/administrators/search",
            {"queries": [{"userIdQuery": {"userId": account_id}}]},
            org_id=resource.get("org", {}).get("orgId")
            or resource.get("projectGrant", {}).get("orgId"),
        )
        assert response is not None  # noqa: S101
        admins = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        for admin in admins:
            if admin.get("userId") == account_id and _matches_resource(
                admin.get("resource"), resource
            ):
                roles = cast("list[object]", admin.get("roles") or [])
                return frozenset(str(role) for role in roles)
        return None

    async def list_administrators(self, organization_id: str) -> list[dict[str, Any]]:
        """Lê todos os administradores da organização para observação."""
        response = await self._connection.call(
            "POST",
            "/v2/administrators/search",
            {"queries": []},
            org_id=organization_id,
        )
        assert response is not None  # noqa: S101
        admins = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        results: list[dict[str, Any]] = []
        for admin in admins:
            user_id = admin.get("userId")
            roles = cast("list[object]", admin.get("roles") or [])
            if user_id:
                results.append(
                    {
                        "accountId": str(user_id),
                        "permissions": sorted(str(r) for r in roles),
                    }
                )
        return results

    async def create_administrator(
        self, account_id: str, resource: dict[str, Any], permissions: Iterable[str]
    ) -> bool:
        response = await self._connection.call(
            "POST",
            "/v2/administrators",
            {"userId": account_id, "roles": list(permissions), "resource": resource},
            accept_conflict=True,
            org_id=resource.get("org", {}).get("orgId")
            or resource.get("projectGrant", {}).get("orgId"),
        )
        return response is not None

    async def update_administrator(
        self, account_id: str, resource: dict[str, Any], permissions: Iterable[str]
    ) -> None:
        await self._connection.call(
            "PUT",
            f"/v2/administrators/{account_id}",
            {"roles": list(permissions), "resource": resource},
            org_id=resource.get("org", {}).get("orgId")
            or resource.get("projectGrant", {}).get("orgId"),
        )


def _matches_resource(candidate: object, target: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        return False
    cand_dict = cast("dict[str, Any]", candidate)
    if cand_dict.get("resourceType") != target.get("resourceType"):
        return False
    if target["resourceType"] == ORGANIZATION_TYPE:
        return cand_dict.get("org", {}).get("orgId") == target["org"]["orgId"]
    if target["resourceType"] == PROJECT_GRANT_TYPE:
        cand_pg = cand_dict.get("projectGrant", {})
        target_pg = target["projectGrant"]
        return (
            cand_pg.get("orgId") == target_pg["orgId"]
            and cand_pg.get("projectId") == target_pg["projectId"]
        )
    return False
