"""Driver de escrita da autorização (roles) do usuário no projeto `roles-ipm`.

API v2 de autorizações (Connect por POST; a organização vai no corpo, decisão 0029). A autorização
é feita no Project Grant de `roles-ipm` para a organização do usuário: o Grant é o teto, e o
Zitadel recusa uma role fora dele (decisão 0077). Uma autorização por usuário. Operações
idempotentes; o driver não decide o que fazer: isso é das `actions/`.
"""

from typing import Any, cast

from ipm_user.executor.domain.identity import Authorization, ProviderError
from ipm_user.executor.provider.identity import IdentityConnection
from ipm_user.executor.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
ALREADY_EXISTING_AUTHORIZATION_ID = "V3-DKcYh"  # autorização já existe (Zitadel v4.19.4)


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._project_id = settings.project_id or ""

    async def authorization(self, user_id: str, organization_id: str) -> Authorization | None:
        """A autorização do usuário em `roles-ipm` na organização dele, ou `None`."""
        response = await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/ListAuthorizations",
            {
                "filters": [
                    {"inUserIds": {"ids": [user_id]}},
                    {"organizationId": {"id": organization_id}},
                ]
            },
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        items = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("authorizations") or []
        )
        for item in items:
            if cast("dict[str, Any]", item.get("project") or {}).get("id") == self._project_id:
                return Authorization(
                    authorization_id=str(item["id"]),
                    roles=frozenset(
                        str(cast("dict[str, Any]", role)["key"])
                        for role in cast("list[Any]", item.get("roles") or [])
                    ),
                )
        return None

    async def create(self, user_id: str, organization_id: str, roles: list[str]) -> None:
        try:
            await self._connection.call(
                "POST",
                f"{AUTHORIZATION_SERVICE}/CreateAuthorization",
                {
                    "userId": user_id,
                    "projectId": self._project_id,
                    "organizationId": organization_id,
                    "roleKeys": roles,
                },
            )
        except ProviderError as error:
            # Repetição de um passo já feito é sucesso (idempotência); as roles certas são
            # conferidas pelo Observer na leitura seguinte.
            if error.reason == "Rejected" and ALREADY_EXISTING_AUTHORIZATION_ID in str(error):
                return
            raise

    async def update(self, authorization_id: str, roles: list[str]) -> None:
        """Substitui a lista de roles da autorização (as que faltarem são revogadas)."""
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/UpdateAuthorization",
            {"id": authorization_id, "roleKeys": roles},
        )

    async def remove(self, authorization_id: str) -> None:
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/DeleteAuthorization",
            {"id": authorization_id},
            accept_not_found=True,
        )
