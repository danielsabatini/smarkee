"""Driver de escrita do usuário no Zitadel (API v2 de usuários, verificada na v4.19.4).

Um sub-recurso, operações pequenas e idempotentes: o `user_id` é o `resourceId`, e a repetição de
um passo já feito é tratada como sucesso (`docs/loop/RESOURCE-CONTROL-LOOP.md` §26). O driver não
decide
o que fazer: isso é das `actions/`. Nenhum dado pessoal entra em mensagens de erro.
"""

from typing import Any, cast

from core_account.executor.domain.identity import IdentityUser, ProviderError
from core_account.executor.provider.identity import IdentityConnection
from core_account.executor.settings import IdentitySettings

ALREADY_EXISTING_ID = "COMMAND-7yiox1isql"  # Errors.Account.AlreadyExisting (Zitadel v4.19.4)


class UserDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    async def get_user(self, user_id: str) -> IdentityUser | None:
        response = await self._connection.call("GET", f"/v2/users/{user_id}", accept_not_found=True)
        if response is None:
            return None
        user = cast("dict[str, Any]", self._connection.json(response).get("user") or {})
        human = cast("dict[str, Any]", user.get("human") or {})
        email = cast("dict[str, Any]", human.get("email") or {})
        return IdentityUser(email=str(email.get("email", "")))

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool:
        """Cria o usuário **sem senha**, com o `resourceId` como ID. `False` se já existe."""
        body = {
            "userId": user_id,
            "organization": {"orgId": self._settings.register_organization_id},
            "username": email,
            "profile": {"givenName": given_name, "familyName": family_name},
            "email": {"email": email},
        }
        try:
            await self._connection.call("POST", "/v2/users/human", body)
        except ProviderError as error:
            if error.reason == "Rejected" and ALREADY_EXISTING_ID in str(error):
                return False
            raise
        return True

    async def delete_user(self, user_id: str) -> None:
        await self._connection.call("DELETE", f"/v2/users/{user_id}", accept_not_found=True)
