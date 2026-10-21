"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from ipm_user.receiver.domain.access import OrganizationAccess
from ipm_user.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_user(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_users(
        self, *, organization_id: str, after: str | None, limit: int
    ) -> list[ResourceRecord]: ...

    async def count_users_in(self, organization_id: str) -> int: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class Organizations(Protocol):
    """Receiver da Organization, consultado com o token do solicitante (decisão 0040)."""

    async def access(self, organization_id: str, access_token: str) -> OrganizationAccess: ...
