"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from bsm_account.api.domain.account import OwnerQuota, UniqueValue
from bsm_account.api.domain.principal import Principal
from bsm_account.api.domain.records import ResourceRecord


class Repository(Protocol):
    async def get_account(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_accounts(
        self, *, owner: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]: ...


class Organizations(Protocol):
    """Projeção local de uso de Billing Accounts por Organizations (decisões 0082 e 0100)."""

    def has_attached_organizations(self, billing_account_id: str) -> bool: ...


class EmailVerifier(Protocol):
    async def is_verified(self, principal: Principal) -> bool: ...


class AdmissionTransaction(Protocol):
    """Gravações da admissão dentro de uma única transação do SSOT (decisão 0098)."""

    async def lock_idempotency(self, requested_by: str, key: str) -> None: ...

    async def find_idempotency(self, requested_by: str, key: str) -> tuple[str, str] | None: ...

    async def record_idempotency(
        self, requested_by: str, key: str, *, request_digest: str, resource_id: str
    ) -> None: ...

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool: ...

    async def owned_count(self, quota: OwnerQuota) -> int: ...

    async def insert_resource(
        self,
        resource_id: str,
        *,
        schema_version: str,
        desired: Mapping[str, Any],
        requested_by: str,
        correlation_id: str,
    ) -> None: ...

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None: ...

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        reconciliation: str,
        expected_resource_version: int,
        requested_by: str,
        correlation_id: str,
    ) -> int | None: ...

    async def delete_resource(self, resource_id: str) -> None: ...

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None: ...

    async def fetch_record(self, resource_id: str) -> ResourceRecord | None: ...


class AdmissionStore(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[AdmissionTransaction]: ...
