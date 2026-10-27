"""Driver de leitura e escrita de metadados no Zitadel (`/v2/metadata`).

Armazena atributos gerenciados como `deletionProtection` da Organization.
Todas as operações operam com menor privilégio passando `org_id=owner_id`.
"""

from typing import Any, cast

from ipm_organization.controller.drivers.identity import IdentityConnection


class MetadataDriver:
    def __init__(self, connection: IdentityConnection) -> None:
        self._connection = connection

    async def get_value(self, owner_id: str, key: str) -> str | None:
        response = await self._connection.call(
            "POST",
            "/v2/metadata/search",
            {"queries": [{"keyQuery": {"key": key}}]},
            accept_not_found=True,
            org_id=owner_id,
        )
        if response is None:
            return None
        entries = cast("list[dict[str, Any]]", self._connection.json(response).get("result") or [])
        for entry in entries:
            if entry.get("key") == key:
                value = entry.get("value")
                return None if value is None else str(value)
        return None

    async def set_value(self, owner_id: str, key: str, value: str) -> None:
        await self._connection.call(
            "POST",
            "/v2/metadata",
            {"metadata": [{"key": key, "value": value}]},
            org_id=owner_id,
        )
