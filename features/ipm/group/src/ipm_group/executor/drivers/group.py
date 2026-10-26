"""Driver de leitura e escrita do Grupo no banco `platform` (decisões 0086 e 0088)."""

from ipm_group.executor.domain.identity import ProviderError, StoredGroup
from ipm_group.executor.provider.storage import StateStoreConnection


class GroupDriver:
    def __init__(self, connection: StateStoreConnection) -> None:
        self._connection = connection

    async def get_group(self, group_id: str) -> StoredGroup | None:
        record = await self._connection.read_record(group_id)
        if record is None:
            return None
        org_id = record.get("organizationId")
        name = record.get("name")
        description = record.get("description")
        roles = record.get("roles")
        protection = record.get("deletionProtection")
        if (
            not isinstance(org_id, str)
            or not isinstance(name, str)
            or not isinstance(description, str)
            or not isinstance(roles, list)
            or not all(isinstance(item, str) for item in roles)  # pyright: ignore[reportUnknownVariableType]
        ):
            raise ProviderError(
                "ExternalError",
                retryable=False,
                detail="stored group is missing required fields",
            )
        return StoredGroup(
            organization_id=org_id,
            name=name,
            description=description,
            roles=[str(item) for item in roles],  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            deletion_protection=protection if isinstance(protection, bool) else False,
        )

    async def save_group(self, group_id: str, group: StoredGroup) -> None:
        await self._connection.write_record(
            group_id,
            {
                "organizationId": group.organization_id,
                "name": group.name,
                "description": group.description,
                "roles": list(group.roles),
                "deletionProtection": group.deletion_protection,
            },
        )

    async def delete_group(self, group_id: str) -> None:
        await self._connection.delete_record(group_id)
