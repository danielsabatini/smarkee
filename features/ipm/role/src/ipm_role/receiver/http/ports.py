"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from ipm_role.receiver.domain.access import OrganizationAccess
from ipm_role.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_role(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_roles(
        self, *, organization_id: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        """Predefinidas (`core`) e, se `organization_id` vier, as `custom` dessa Organization."""
        ...

    async def count_custom_roles_in(self, organization_id: str) -> int: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class Organizations(Protocol):
    """Receiver da Organization, consultado com o token do solicitante (decisão 0040)."""

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess: ...


class Users(Protocol):
    """Receiver de User, consultado para descobrir a Organization do solicitante."""

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None: ...


class RoleUsage(Protocol):
    """Receivers de User e Group, consultados para saber se uma Role está em uso."""

    async def role_in_use(
        self, organization_id: str, role_name: str, access_token: str
    ) -> bool: ...
