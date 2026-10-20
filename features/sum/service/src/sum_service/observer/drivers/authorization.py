"""Driver de leitura da autorização (roles) do usuário nos projetos de roles do Zitadel.

Espelho do driver de escrita do Executor (`executor/drivers/authorization.py`): o mesmo
sub-recurso, só leitura (API v2 de autorizações, na organização `register`).
"""

from typing import Any, cast

from sum_service.observer.domain.authorization import Authorization
from sum_service.observer.provider.identity import IdentityConnection
from sum_service.observer.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    async def authorizations(self, user_id: str) -> list[Authorization]:
        """Autorizações do usuário nos projetos de roles configurados, na organização `register`."""
        response = await self._connection.request(
            "POST",
            f"{AUTHORIZATION_SERVICE}/ListAuthorizations",
            {
                "filters": [
                    {"inUserIds": {"ids": [user_id]}},
                    {"organizationId": {"id": self._settings.register_organization_id}},
                ]
            },
        )
        assert response is not None  # noqa: S101 (sem absence_on_not_found)
        configured = set(self._settings.project_ids.values())
        items = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("authorizations") or []
        )
        found: list[Authorization] = []
        for item in items:
            project_id = str(cast("dict[str, Any]", item["project"])["id"])
            if project_id not in configured:
                continue
            roles = frozenset(
                str(cast("dict[str, Any]", role)["key"])
                for role in cast("list[Any]", item.get("roles") or [])
            )
            found.append(Authorization(project_id, roles))
        return found
