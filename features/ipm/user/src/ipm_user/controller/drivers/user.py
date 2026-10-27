"""Driver de leitura e escrita do usuário da Organization no Zitadel (API v2, v4.19.4).

Reaproveita os endpoints verificados do Executor e do Observer (decisões 0077 e 0096). O `user_id`
é o `resourceId`; repetir um passo já feito é sucesso. O usuário nasce na organização do cliente, e
o Zitadel recusa qualquer organização em que a conta do Controller não tem `ORG_USER_CREATOR`. A
criação não envia senha: o Zitadel manda o e-mail de verificação, que também define a senha. Nenhum
dado pessoal entra em mensagens de erro. O driver não decide o que fazer.
"""

from dataclasses import dataclass
from typing import Any, cast

from ipm_user.controller.drivers.identity import IdentityConnection, ProviderError

ALREADY_EXISTING_ID = "COMMAND-7yiox1isql"  # Errors.Account.AlreadyExisting (Zitadel v4.19.4)


@dataclass(frozen=True, slots=True)
class IdentityUser:
    """Usuário humano lido do provedor."""

    email: str
    organization_id: str
    """Organização do provedor dona do usuário (`resourceOwner`)."""

    state: str
    email_verified: bool
    password_set: bool


class UserDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_user(self, user_id: str) -> IdentityUser | None:
        """O usuário, ou `None` se o Zitadel confirmou (404) que ele não existe."""
        response = await self._connection.call("GET", f"/v2/users/{user_id}", accept_not_found=True)
        if response is None:
            return None
        user = cast("dict[str, Any]", self._connection.json(response).get("user") or {})
        details = cast("dict[str, Any]", user.get("details") or {})
        human = cast("dict[str, Any]", user.get("human") or {})
        email = cast("dict[str, Any]", human.get("email") or {})
        return IdentityUser(
            email=str(email.get("email", "")),
            organization_id=str(details.get("resourceOwner", "")),
            state=str(user.get("state", "")),
            email_verified=email.get("isVerified") is True,
            password_set="passwordChanged" in human,
        )

    async def create_user(
        self,
        user_id: str,
        *,
        organization_id: str,
        given_name: str,
        family_name: str,
        email: str,
    ) -> bool:
        """Cria o usuário **sem senha**, com o `resourceId` como ID. `False` se já existe."""
        body = {
            "userId": user_id,
            "organization": {"orgId": organization_id},
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
