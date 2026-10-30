"""Driver de leitura e escrita do usuário da Account no Zitadel (API v2, verificada na v4.19.4).

Reaproveita os endpoints verificados do Executor e do Observer (decisões 0014 e 0096). O `user_id` é
o `resourceId`; repetir um passo já feito é sucesso. O usuário nasce na organização `register`. A
criação não envia senha: o Zitadel manda o e-mail de verificação, cuja página também define a senha.
Nenhum dado pessoal entra em mensagens de erro. O driver não decide o que fazer.
"""

from dataclasses import dataclass
from typing import Any, cast

from core_account.controller.drivers.identity import IdentityConnection, ProviderError
from core_account.controller.settings import IdentitySettings

ALREADY_EXISTING_ID = "COMMAND-7yiox1isql"  # Errors.Account.AlreadyExisting (Zitadel v4.19.4)


@dataclass(frozen=True, slots=True)
class IdentityUser:
    """Usuário humano lido do provedor."""

    email: str
    state: str
    email_verified: bool
    password_set: bool


class UserDriver:
    def __init__(self, connection: IdentityConnection, settings: IdentitySettings) -> None:
        self._connection = connection
        self._settings = settings

    async def get_user(self, user_id: str) -> IdentityUser | None:
        """O usuário, ou `None` se o Zitadel confirmou (404) que ele não existe."""
        response = await self._connection.call("GET", f"/v2/users/{user_id}", accept_not_found=True)
        if response is None:
            return None
        user = cast("dict[str, Any]", self._connection.json(response).get("user") or {})
        human = cast("dict[str, Any]", user.get("human") or {})
        email = cast("dict[str, Any]", human.get("email") or {})
        return IdentityUser(
            email=str(email.get("email", "")),
            state=str(user.get("state", "")),
            email_verified=email.get("isVerified") is True,
            password_set="passwordChanged" in human,
        )

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

    async def resend_activation(self, user_id: str) -> bool:
        """Reenvia o e-mail de ativação/verificação para o usuário (API v2)."""
        try:
            path = f"/v2/users/{user_id}/email/resend"
            await self._connection.call("POST", path, {"sendCode": {}})
        except ProviderError as error:
            if error.reason in ("NotFound", "Rejected"):
                return False
            raise
        return True

    async def delete_user(self, user_id: str) -> None:
        await self._connection.call("DELETE", f"/v2/users/{user_id}", accept_not_found=True)

