"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from ipm_organization.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_organization(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_organizations(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]: ...

    async def count_organizations_owned_by(self, owner: str) -> int: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class Users(Protocol):
    """Receiver do User, consultado com o token do solicitante (decisões 0040 e 0077)."""

    async def organization_of(self, user_id: str, access_token: str) -> str | None: ...

    async def has_users(self, organization_id: str, access_token: str) -> bool: ...
