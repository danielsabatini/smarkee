"""Driver de leitura da Role no armazenamento de estado (decisões 0073 e 0083)."""

from ipm_role.observer.domain.identity import ProviderError, StoredRole
from ipm_role.observer.provider.storage import StateStoreConnection


class RoleDriver:
    def __init__(self, connection: StateStoreConnection) -> None:
        self._connection = connection

    async def get_role(self, role_id: str) -> StoredRole | None:
        record = await self._connection.read_record(role_id)
        if record is None:
            return None
        name = record.get("name")
        description = record.get("description")
        permissions = record.get("permissions")
        protection = record.get("deletionProtection")
        if (
            not isinstance(name, str)
            or not isinstance(description, str)
            or not isinstance(permissions, list)
            or not all(isinstance(item, str) for item in permissions)  # pyright: ignore[reportUnknownVariableType]
        ):
            raise ProviderError("stored role is missing required fields")
        return StoredRole(
            name=name,
            description=description,
            permissions=[str(item) for item in permissions],  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            deletion_protection=protection if isinstance(protection, bool) else None,
        )
