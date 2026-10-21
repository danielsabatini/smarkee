"""Driver de leitura do usuário no Zitadel (API v2 de usuários).

Espelho do driver de escrita do Executor (`executor/drivers/user.py`): o mesmo sub-recurso, só
leitura. Só um 404 do usuário exato é ausência.
"""

from typing import Any, cast

from ipm_user.observer.domain.identity import IdentityUser
from ipm_user.observer.provider.identity import IdentityConnection


class UserDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_user(self, user_id: str) -> IdentityUser | None:
        """O usuário, ou `None` se o Zitadel confirmou (404) que ele não existe."""
        response = await self._connection.request(
            "GET", f"/v2/users/{user_id}", absence_on_not_found=True
        )
        if response is None:
            return None
        document = self._connection.json(response)
        user = cast("dict[str, Any]", document.get("user") or {})
        human = cast("dict[str, Any]", user.get("human") or {})
        email = cast("dict[str, Any]", human.get("email") or {})
        return IdentityUser(
            state=str(user.get("state", "")),
            email_verified=email.get("isVerified") is True,
            password_set="passwordChanged" in human,
        )
