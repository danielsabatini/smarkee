"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from ipm_role.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_role(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_roles(self, *, after: str | None, limit: int) -> list[ResourceRecord]: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...
