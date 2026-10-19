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
