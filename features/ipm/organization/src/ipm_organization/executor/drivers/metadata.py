"""Driver de escrita do metadado no Zitadel (API v2, verificada na v4.19.4; decisão 0074).

Um sub-recurso, compartilhado por organização e usuário: o dono é informado na construção
(`organizations` ou `users`). `SetOrganizationMetadata` e `SetUserMetadata` sobrescrevem só as
chaves enviadas e repetir a gravação é sucesso, então a operação é idempotente. O valor vai em
base64, como a API exige. O driver não decide o que gravar: isso é das `actions/`.
"""

import base64
from typing import Literal

from ipm_organization.executor.provider.identity import IdentityConnection

Owner = Literal["organizations", "users"]


class MetadataDriver:
    def __init__(self, connection: IdentityConnection, owner: Owner) -> None:
        self._connection = connection
        self._owner = owner

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        """Grava `key = value` no dono, sem tocar nas outras chaves."""
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        await self._connection.call(
            "POST",
            f"/v2/{self._owner}/{owner_id}/metadata",
            {"metadata": [{"key": key, "value": encoded}]},
        )
