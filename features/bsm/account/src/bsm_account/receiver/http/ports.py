"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from typing import Protocol

from bsm_account.receiver.domain.records import OperationRecord, ResourceRecord


class Repository(Protocol):
    async def get_account(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_accounts(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]: ...

    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class Organizations(Protocol):
    """Receiver de Organization, consultado com o token do solicitante (decisões 0040 e 0082)."""

    async def has_organizations(self, billing_account_id: str, access_token: str) -> bool: ...
