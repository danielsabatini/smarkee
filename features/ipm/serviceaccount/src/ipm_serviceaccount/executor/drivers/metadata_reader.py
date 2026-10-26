"""Driver de leitura do metadado do usuário no Zitadel, para o próprio Executor (decisão 0094).

O Zitadel não devolve a chave pública que recebeu, então o Executor guarda no metadado `keys` o
mapa `fingerprint -> keyId` e o lê antes de alterá-lo, para a operação ser idempotente. Espelho
do driver de leitura do Observer; qualquer falha vira `ProviderError`.
"""

import base64
import binascii
from typing import Any, cast

from ipm_serviceaccount.executor.domain.identity import ProviderError
from ipm_serviceaccount.executor.provider.identity import IdentityConnection


class MetadataReader:
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
        document = self._connection.json(response)
        entries = cast("list[dict[str, Any]]", document.get("metadata") or [])
        for entry in entries:
            if entry.get("key") == key:
                try:
                    return base64.b64decode(str(entry.get("value", "")), validate=True).decode()
                except binascii.Error, UnicodeDecodeError:
                    raise ProviderError(
                        "ProviderUnavailable", retryable=True, detail="invalid metadata value"
                    ) from None
        return None
