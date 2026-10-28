"""Driver de leitura do usuário no Zitadel (API v2, verificada na v4.19.4).

A ligação de serviço só concede permissões a um usuário que já existe: o Controller não cria nem
remove usuários (isso é da Account). Só a confirmação (404) de que o usuário não existe é ausência;
qualquer outra falha é erro do provedor. O driver não decide o que fazer.
"""

from sum_service.controller.drivers.identity import IdentityConnection


class UserDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def exists(self, user_id: str) -> bool:
        """`False` só se o Zitadel confirmou (404) que o usuário não existe."""
        response = await self._connection.call("GET", f"/v2/users/{user_id}", accept_not_found=True)
        return response is not None
