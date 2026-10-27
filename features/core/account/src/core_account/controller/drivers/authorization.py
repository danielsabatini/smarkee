"""Driver de leitura e escrita da autorização (permissões) nos projetos de permissões do Zitadel.

Reaproveita os endpoints verificados do Executor e do Observer (decisões 0029, 0032 e 0096). API v2
de autorizações (Connect por POST; a organização vai no corpo). No Zitadel, cada permissão da
Smarkee é uma Project Role (`roleKeys`; `docs/identity/PERMISSION.md`). Cada módulo tem o próprio
projeto, e o Controller só concede nos projetos de `project_ids` (`PROJECT_GRANT_OWNER` nos Grants
deles); o Zitadel nega qualquer outro. Operações idempotentes; o driver não decide o que fazer.
"""

from dataclasses import dataclass
from typing import Any, cast

from core_account.controller.drivers.identity import IdentityConnection, ProviderError
from core_account.controller.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
ALREADY_EXISTING_AUTHORIZATION_ID = "V3-DKcYh"  # autorização já existe (Zitadel v4.19.4)


@dataclass(frozen=True, slots=True)
class Grant:
    """Autorização do usuário em um projeto de permissões (uma por projeto)."""

    grant_id: str
    project_id: str
    permissions: frozenset[str]


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    def project_of(self, permission: str) -> str:
        """Projeto da permissão (módulo = primeiro segmento). Módulo não configurado: erro."""
        module = permission.split(".", 1)[0]
        project_id = self._settings.project_ids.get(module)
        if project_id is None:
            raise ProviderError(
                "Rejected", retryable=False, detail=f"no permissions project for module {module}"
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
                permissions=frozenset(
                    str(cast("dict[str, Any]", role)["key"])
                    for role in cast("list[Any]", item.get("roles") or [])
                ),
            )
            for item in items
            if cast("dict[str, Any]", item["project"])["id"] in configured
        ]

    async def create_grant(self, user_id: str, project_id: str, permissions: list[str]) -> None:
        try:
            await self._connection.call(
                "POST",
                f"{AUTHORIZATION_SERVICE}/CreateAuthorization",
                {
                    "userId": user_id,
                    "projectId": project_id,
                    "organizationId": self._settings.register_organization_id,
                    "roleKeys": permissions,
                },
            )
        except ProviderError as error:
            # Repetição de um passo já feito é sucesso; a permissão certa é conferida na leitura.
            if error.reason == "Rejected" and ALREADY_EXISTING_AUTHORIZATION_ID in str(error):
                return
            raise

    async def update_grant(self, grant_id: str, permissions: list[str]) -> None:
        """Substitui a lista de permissões da autorização (as que faltarem são revogadas)."""
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/UpdateAuthorization",
            {"id": grant_id, "roleKeys": permissions},
        )

    async def remove_grant(self, grant_id: str) -> None:
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/DeleteAuthorization",
            {"id": grant_id},
            accept_not_found=True,
        )
