"""Driver de leitura e escrita da Role no armazenamento de estado (decisão 0073)."""

from ipm_role.executor.domain.identity import ProviderError, StoredRole
from ipm_role.executor.provider.storage import StateStoreConnection


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
            raise ProviderError(
                "ExternalError",
                retryable=False,
                detail="stored role is missing required fields",
            )
        return StoredRole(
            name=name,
            description=description,
            permissions=[str(item) for item in permissions],  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            deletion_protection=protection if isinstance(protection, bool) else True,
        )

    async def save_role(self, role_id: str, role: StoredRole) -> None:
        await self._connection.write_record(
            role_id,
            {
                "name": role.name,
                "description": role.description,
                "permissions": list(role.permissions),
                "deletionProtection": role.deletion_protection,
            },
        )

    async def delete_role(self, role_id: str) -> None:
        await self._connection.delete_record(role_id)
