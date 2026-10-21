"""Driver de leitura do metadado no Zitadel (API v2, verificada na v4.19.4; decisão 0074).

Espelho do driver de escrita do Executor (`executor/drivers/metadata.py`): o mesmo sub-recurso, só
leitura, para organização ou usuário (o dono é informado na construção). Qualquer falha de leitura
vira `ProviderError`, e o chamador a trata como `unknown`.
"""

import base64
import binascii
from typing import Any, Literal, cast

from ipm_user.observer.domain.identity import ProviderError
from ipm_user.observer.provider.identity import IdentityConnection

Owner = Literal["organizations", "users"]


class MetadataDriver:
    def __init__(self, connection: IdentityConnection, owner: Owner) -> None:
        self._connection = connection
        self._owner = owner

    async def get_value(self, owner_id: str, key: str) -> str | None:
        """O valor de `key` no dono, ou `None` se a chave não existe."""
        response = await self._connection.request(
            "POST",
            f"/v2/{self._owner}/{owner_id}/metadata/search",
            {"filters": [{"keyFilter": {"key": key}}]},
        )
        assert response is not None  # noqa: S101 (a busca vazia é 200, nunca 404)
        document = self._connection.json(response)
        entries = cast("list[dict[str, Any]]", document.get("metadata") or [])
        for entry in entries:
            if entry.get("key") == key:
                try:
                    return base64.b64decode(str(entry.get("value", "")), validate=True).decode()
                except binascii.Error, UnicodeDecodeError:
                    raise ProviderError("invalid metadata value") from None
        return None
