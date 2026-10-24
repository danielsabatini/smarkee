"""Driver de leitura da autorização (permissões) do usuário nos projetos do Zitadel.

Espelho do driver de escrita do Executor (`executor/drivers/authorization.py`): o mesmo
sub-recurso, só leitura (API v2 de autorizações). No Zitadel, cada permissão da Smarkee é uma
Project Role (`docs/identity/PERMISSION.md`).
"""

from typing import Any, cast

from core_account.observer.provider.identity import IdentityConnection
from core_account.observer.settings import IdentitySettings

AUTHORIZATION_SERVICE = "/zitadel.authorization.v2.AuthorizationService"


class AuthorizationDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    async def granted_permissions(self, user_id: str) -> set[str]:
        """União das permissões do usuário em todos os projetos de permissões.

        Há um projeto por módulo (decisão 0032); a leitura é pela organização `register`,
        sem filtrar o projeto, para o Observer não depender da lista de módulos.
        """
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
        permissions: set[str] = set()
        authorizations = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("authorizations") or []
        )
        for authorization in authorizations:
            permissions.update(
                str(cast("dict[str, Any]", role)["key"])
                for role in cast("list[Any]", authorization.get("roles") or [])
            )
        return permissions
