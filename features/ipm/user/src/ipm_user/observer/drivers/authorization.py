"""Driver de leitura da autorização (roles) do usuário no projeto `roles-ipm`.

Espelho do driver de escrita do Executor (`executor/drivers/authorization.py`): o mesmo
sub-recurso, só leitura (API v2 de autorizações).
"""

from typing import Any, cast

from ipm_user.observer.provider.identity import IdentityConnection
from ipm_user.observer.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._project_id = settings.project_id or ""

    async def granted_roles(self, user_id: str) -> set[str]:
        """Roles do usuário em `roles-ipm` (as autorizações de outros projetos não contam)."""
        response = await self._connection.request(
            "POST",
            f"{AUTHORIZATION_SERVICE}/ListAuthorizations",
            {"filters": [{"inUserIds": {"ids": [user_id]}}]},
        )
        assert response is not None  # noqa: S101 (sem absence_on_not_found)
        roles: set[str] = set()
        authorizations = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("authorizations") or []
        )
        for authorization in authorizations:
            project = cast("dict[str, Any]", authorization.get("project") or {})
            if project.get("id") != self._project_id:
                continue
            roles.update(
                str(cast("dict[str, Any]", role)["key"])
                for role in cast("list[Any]", authorization.get("roles") or [])
            )
        return roles
