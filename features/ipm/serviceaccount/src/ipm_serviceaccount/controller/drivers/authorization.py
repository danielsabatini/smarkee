"""Driver de leitura e escrita da autorização (permissões) do usuário no projeto `roles-ipm`.

Reaproveita os endpoints verificados do Executor e do Observer (decisões 0029, 0077 e 0096). API v2
de autorizações (Connect por POST; a organização vai no corpo). A autorização é feita no Project
Grant de `roles-ipm` para a organização do usuário: o Grant é o teto, e o Zitadel recusa uma
permissão fora dele. No Zitadel, cada permissão da Smarkee é uma Project Role (`roleKeys`;
`docs/identity/PERMISSION.md`). Uma autorização por usuário. O driver não decide o que fazer.
"""

from dataclasses import dataclass
from typing import Any, cast

from ipm_serviceaccount.controller.drivers.identity import IdentityConnection, ProviderError

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"
ALREADY_EXISTING_AUTHORIZATION_ID = "V3-DKcYh"  # autorização já existe (Zitadel v4.19.4)


@dataclass(frozen=True, slots=True)
class Authorization:
    """Autorização da máquina no projeto `roles-ipm`, na organização dela (uma só)."""

    authorization_id: str
    permissions: frozenset[str]


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, project_id: str) -> None:
        self._connection = connection
        self._project_id = project_id

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
                    permissions=frozenset(
                        str(cast("dict[str, Any]", role)["key"])
                        for role in cast("list[Any]", item.get("roles") or [])
                    ),
                )
        return None

    async def granted_permissions(self, user_id: str) -> set[str]:
        """Permissões do usuário em `roles-ipm` (as autorizações de outros projetos não contam)."""
        response = await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/ListAuthorizations",
            {"filters": [{"inUserIds": {"ids": [user_id]}}]},
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        permissions: set[str] = set()
        authorizations = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("authorizations") or []
        )
        for authorization in authorizations:
            project = cast("dict[str, Any]", authorization.get("project") or {})
            if project.get("id") != self._project_id:
                continue
            permissions.update(
                str(cast("dict[str, Any]", role)["key"])
                for role in cast("list[Any]", authorization.get("roles") or [])
            )
        return permissions

    async def create(self, user_id: str, organization_id: str, permissions: list[str]) -> None:
        try:
            await self._connection.call(
                "POST",
                f"{AUTHORIZATION_SERVICE}/CreateAuthorization",
                {
                    "userId": user_id,
                    "projectId": self._project_id,
                    "organizationId": organization_id,
                    "roleKeys": permissions,
                },
            )
        except ProviderError as error:
            # Repetir um passo já feito é sucesso (idempotência); as permissões certas são
            # conferidas na leitura seguinte.
            if error.reason == "Rejected" and ALREADY_EXISTING_AUTHORIZATION_ID in str(error):
                return
            raise

    async def update(self, authorization_id: str, permissions: list[str]) -> None:
        """Substitui a lista de permissões da autorização (as que faltarem são revogadas)."""
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/UpdateAuthorization",
            {"id": authorization_id, "roleKeys": permissions},
        )

    async def remove(self, authorization_id: str) -> None:
        await self._connection.call(
            "POST",
            f"{AUTHORIZATION_SERVICE}/DeleteAuthorization",
            {"id": authorization_id},
            accept_not_found=True,
        )
