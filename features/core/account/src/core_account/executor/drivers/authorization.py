"""Driver de escrita da autorização (roles) nos projetos de roles do Zitadel.

API v2 de autorizações (Connect por POST; a organização vai no corpo, decisão 0029). Cada módulo
tem o próprio projeto de roles, e o Executor só concede nos projetos de `project_ids`
(`PROJECT_GRANT_OWNER` nos Grants deles). O Zitadel nega qualquer outro (decisão 0032).
Operações idempotentes; o driver não decide o que fazer: isso é das `actions/`.
"""

from typing import Any, cast

from core_account.executor.domain.identity import Grant, ProviderError
from core_account.executor.provider.identity import IdentityConnection
from core_account.executor.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
ALREADY_EXISTING_AUTHORIZATION_ID = "V3-DKcYh"  # autorização já existe (Zitadel v4.19.4)


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    def project_of(self, role: str) -> str:
        """Projeto de roles da role (módulo = primeiro segmento). Módulo não configurado: erro."""
        module = role.split(".", 1)[0]
        project_id = self._settings.project_ids.get(module)
        if project_id is None:
            raise ProviderError(
                "Rejected", retryable=False, detail=f"no roles project for module {module}"
            )
        return project_id

    async def grants(self, user_id: str) -> list[Grant]:
        """Autorizações do usuário nos projetos configurados (uma por projeto)."""
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
        assert response is not None  # noqa: S101 (sem accept_not_found)
        configured = set(self._settings.project_ids.values())
        items = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("authorizations") or []
        )
        return [
            Grant(
                grant_id=str(item["id"]),
                project_id=str(cast("dict[str, Any]", item["project"])["id"]),
                roles=frozenset(
                    str(cast("dict[str, Any]", r)["key"])
                    for r in cast("list[Any]", item.get("roles") or [])
                ),
            )
            for item in items
            if cast("dict[str, Any]", item["project"])["id"] in configured
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
            # Repetição de um passo já feito é sucesso (idempotência); a role certa é conferida
            # pelo Observer na leitura seguinte.
            if error.reason == "Rejected" and ALREADY_EXISTING_AUTHORIZATION_ID in str(error):
                return
            raise

    async def update_grant(self, grant_id: str, roles: list[str]) -> None:
        """Substitui a lista de roles da autorização (as que faltarem são revogadas)."""
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
