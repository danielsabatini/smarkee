"""Portas que a camada HTTP de Group exige dos adaptadores (decisão 0088)."""

from typing import Protocol

from ipm_group.receiver.domain.access import OrganizationAccess
from ipm_group.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_group(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_groups(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]: ...

    async def count_groups_in(self, organization_id: str) -> int: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class Organizations(Protocol):
    """Receiver da Organization, consultado com o token do solicitante (decisão 0040)."""

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess: ...


class Users(Protocol):
    """Receiver de User, consultado para verificar usuários e associação."""

    async def count_users_with_group(
        self, organization_id: str, group_name: str, access_token: str
    ) -> int: ...

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None: ...
