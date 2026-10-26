"""Driver de leitura da service account (machine user) no Zitadel (API v2 de usuários).

Espelho do driver de escrita do Executor (`executor/drivers/serviceaccount.py`): o mesmo
sub-recurso, só leitura. Só um 404 do usuário exato é ausência. Nenhum material de chave é lido:
o `ListKeys` devolve apenas identificador e vencimento.
"""

from typing import Any, cast

from ipm_serviceaccount.observer.domain.identity import IdentityKey, IdentityMachine
from ipm_serviceaccount.observer.provider.identity import IdentityConnection

USER_SERVICE = "/zitadel.user.v2.UserService"


class ServiceAccountDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_machine(self, user_id: str) -> IdentityMachine | None:
        """A máquina, ou `None` se o Zitadel confirmou (404) que ela não existe."""
        response = await self._connection.request(
            "GET", f"/v2/users/{user_id}", absence_on_not_found=True
        )
        if response is None:
            return None
        user = cast("dict[str, Any]", self._connection.json(response).get("user") or {})
        machine = cast("dict[str, Any]", user.get("machine") or {})
        return IdentityMachine(
            state=str(user.get("state", "")),
            access_token_type=str(machine.get("accessTokenType", "")),
        )

    async def list_keys(self, user_id: str) -> list[IdentityKey]:
        """Chaves vigentes da máquina (a vencida some da lista do provedor)."""
        response = await self._connection.request(
            "POST",
            f"{USER_SERVICE}/ListKeys",
            {"filters": [{"userIdFilter": {"id": user_id}}]},
        )
        assert response is not None  # noqa: S101 (sem absence_on_not_found)
        items = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        return [
            IdentityKey(
                key_id=str(item["id"]),
                expires_at=str(item["expirationDate"]) if item.get("expirationDate") else None,
            )
            for item in items
            if "id" in item
        ]
