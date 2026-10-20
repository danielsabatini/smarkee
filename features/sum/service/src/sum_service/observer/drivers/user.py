"""Driver de leitura do usuário no Zitadel (API v2 de usuários): só a existência.

O `sum.service` não escreve o usuário (é da Account); o Observer só confere se ele existe.
"""

from sum_service.observer.provider.identity import IdentityConnection


class UserDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def user_exists(self, user_id: str) -> bool:
        """`False` só se o Zitadel confirmou (404 com detalhe) que o usuário não existe."""
        response = await self._connection.request(
            "GET", f"/v2/users/{user_id}", absence_on_not_found=True
        )
        return response is not None
