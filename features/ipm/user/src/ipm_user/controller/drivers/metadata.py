"""Driver de leitura e escrita do metadado do usuário no Zitadel (API v2, v4.19.4).

Reaproveita os drivers verificados do Executor e do Observer (decisões 0074, 0077 e 0096).
`SetUserMetadata` sobrescreve só as chaves enviadas e repetir a gravação é sucesso (idempotente).
O valor trafega em base64, como a API exige. Falha de leitura vira `ProviderError`, e a observação
a trata como `unknown`.
"""

import base64
import binascii
from typing import Any, cast

from ipm_user.controller.drivers.identity import IdentityConnection, ProviderError


class MetadataDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_value(self, owner_id: str, key: str) -> str | None:
        """O valor de `key` no usuário, ou `None` se a chave não existe."""
        response = await self._connection.call(
            "POST",
            f"/v2/users/{owner_id}/metadata/search",
            {"filters": [{"keyFilter": {"key": key}}]},
        )
        assert response is not None  # noqa: S101 (a busca vazia é 200, nunca 404)
        entries = cast(
            "list[dict[str, Any]]", self._connection.json(response).get("metadata") or []
        )
        for entry in entries:
            if entry.get("key") == key:
                try:
                    return base64.b64decode(str(entry.get("value", "")), validate=True).decode()
                except binascii.Error, UnicodeDecodeError:
                    raise ProviderError(
                        "ProviderUnavailable", retryable=True, detail="invalid metadata value"
                    ) from None
        return None

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        """Grava `key = value` no usuário, sem tocar nas outras chaves."""
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        await self._connection.call(
            "POST",
            f"/v2/users/{owner_id}/metadata",
            {"metadata": [{"key": key, "value": encoded}]},
        )
