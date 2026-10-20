"""Driver de escrita da autorização (roles) nos projetos de roles do Zitadel (decisões 0032 e 0033).

API v2 de autorizações, na organização `register`. Operações idempotentes: repetir uma concessão
já feita é sucesso, e revogar algo que não existe também. O driver não decide o que conceder: isso
é das `actions/`.
"""

from typing import Any, cast

from sum_service.executor.domain.identity import Grant, ProviderError
from sum_service.executor.provider.identity import IdentityConnection
from sum_service.executor.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
ALREADY_EXISTING_AUTHORIZATION_ID = "V3-DKcYh"  # autorização já existe (Zitadel v4.19.4)


def module_of(role: str) -> str:
    return role.split(".", 1)[0]


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    def project_of(self, role: str) -> str:
        """Projeto de roles do módulo da role. Módulo sem projeto configurado: recusa explícita."""
        project_id = self._settings.project_ids.get(module_of(role))
        if project_id is None:
            raise ProviderError(
                "Rejected", retryable=False, detail=f"no roles project for module {module_of(role)}"
            )
        return project_id

    async def grants(self, user_id: str) -> list[Grant]:
        """Autorizações do usuário nos projetos configurados, na organização `register`."""
        response = await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/ListAuthorizations",
            {
                "filters": [
                    {"inUserIds": {"ids": [user_id]}},
                    {"organizationId": {"id": self._settings.register_organization_id}},
                ]
            },
        )
        configured = set(self._settings.project_ids.values())
        items = cast("list[dict[str, Any]]", response.get("authorizations") or [])
        return [
            Grant(
                grant_id=str(item["id"]),
                project_id=str(cast("dict[str, Any]", item["project"])["id"]),
                roles=frozenset(
                    str(cast("dict[str, Any]", role)["key"])
                    for role in cast("list[Any]", item.get("roles") or [])
                ),
            )
            for item in items
            if str(cast("dict[str, Any]", item["project"])["id"]) in configured
        ]

    async def create_grant(self, user_id: str, project_id: str, roles: list[str]) -> None:
        try:
            await self._connection.call(
                "POST",
                f"{AUTHORIZATION_SERVICE}/CreateAuthorization",
                {
                    "userId": user_id,
                    "projectId": project_id,
                    "organizationId": self._settings.register_organization_id,
                    "roleKeys": roles,
                },
            )
        except ProviderError as error:
            if error.reason == "Rejected" and ALREADY_EXISTING_AUTHORIZATION_ID in str(error):
                return
            raise

    async def update_grant(self, grant_id: str, roles: list[str]) -> None:
        """Substitui a lista de roles da autorização."""
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/UpdateAuthorization",
            {"id": grant_id, "roleKeys": roles},
        )

    async def remove_grant(self, grant_id: str) -> None:
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/DeleteAuthorization",
            {"id": grant_id},
            accept_not_found=True,
        )
