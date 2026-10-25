"""Portas do Receiver HTTP: leitura das views do SSOT."""

from typing import Protocol

from ipm_permission.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_permission(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_permissions(self, *, after: str | None, limit: int) -> list[ResourceRecord]: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...
