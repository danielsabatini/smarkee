"""Driver de escrita da service account (machine user) no Zitadel (API v2, verificada na v4.19.4).

Um sub-recurso, operações pequenas e idempotentes: o `user_id` é o `resourceId` e a repetição de um
passo já feito é sucesso (`docs/loop/RESOURCE-CONTROL-LOOP.md` §26). A máquina nasce na organização
do cliente, e o Zitadel recusa qualquer organização em que o Executor não tem `ORG_USER_CREATOR`
(decisão 0094). O `accessTokenType` é sempre `ACCESS_TOKEN_TYPE_JWT`: o padrão do Zitadel é opaco e
o gateway só aceita JWT. O driver não decide o que fazer: isso é das `actions/`. Nenhum material de
chave privada existe aqui, e a chave pública entra apenas em base64 no corpo da chamada.
"""

import base64
from typing import Any, cast

from ipm_serviceaccount.executor.domain.identity import IdentityMachine, ProviderError
from ipm_serviceaccount.executor.provider.identity import IdentityConnection

ALREADY_EXISTING_ID = "COMMAND-7yiox1isql"  # Errors.Account.AlreadyExisting (Zitadel v4.19.4)
ACCESS_TOKEN_TYPE_JWT = "ACCESS_TOKEN_TYPE_JWT"
USER_SERVICE = "/zitadel.user.v2.UserService"


class ServiceAccountDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_machine(self, user_id: str) -> IdentityMachine | None:
        response = await self._connection.call("GET", f"/v2/users/{user_id}", accept_not_found=True)
        if response is None:
            return None
        user = cast("dict[str, Any]", self._connection.json(response).get("user") or {})
        details = cast("dict[str, Any]", user.get("details") or {})
        machine = cast("dict[str, Any]", user.get("machine") or {})
        return IdentityMachine(
            organization_id=str(details.get("resourceOwner", "")),
            access_token_type=str(machine.get("accessTokenType", "")),
        )

    async def create_machine(
        self, user_id: str, *, organization_id: str, username: str, name: str
    ) -> bool:
        """Cria a máquina com o `resourceId` como ID e token JWT. `False` se já existe."""
        body = {
            "userId": user_id,
            "organizationId": organization_id,
            "username": username,
            "machine": {"name": name, "accessTokenType": ACCESS_TOKEN_TYPE_JWT},
        }
        try:
            await self._connection.call("POST", "/v2/users/new", body)
        except ProviderError as error:
            if error.reason == "Rejected" and ALREADY_EXISTING_ID in str(error):
                return False
            raise
        return True

    async def delete_machine(self, user_id: str) -> None:
        await self._connection.call("DELETE", f"/v2/users/{user_id}", accept_not_found=True)

    async def list_key_ids(self, user_id: str) -> set[str]:
        """IDs das chaves da máquina no provedor (a vencida some da lista)."""
        response = await self._connection.call(
            "POST",
            f"{USER_SERVICE}/ListKeys",
            {"filters": [{"userIdFilter": {"id": user_id}}]},
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        items = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        return {str(item["id"]) for item in items if "id" in item}

    async def add_key(self, user_id: str, *, public_key: str, expires_at: str) -> str:
        """Registra a chave PÚBLICA (PEM em base64) com vencimento; devolve o `keyId`."""
        encoded = base64.b64encode(public_key.encode("ascii")).decode("ascii")
        response = await self._connection.call(
            "POST",
            f"/v2/users/{user_id}/keys",
            {"publicKey": encoded, "expirationDate": expires_at},
        )
        assert response is not None  # noqa: S101 (sem accept_not_found)
        key_id = self._connection.json(response).get("keyId")
        if not isinstance(key_id, str) or not key_id:
            raise ProviderError("ProviderUnavailable", retryable=True, detail="no keyId")
        return key_id

    async def remove_key(self, user_id: str, key_id: str) -> None:
        await self._connection.call(
            "DELETE", f"/v2/users/{user_id}/keys/{key_id}", accept_not_found=True
        )
