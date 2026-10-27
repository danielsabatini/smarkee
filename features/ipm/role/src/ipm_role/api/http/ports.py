"""Portas que a camada HTTP exige dos adaptadores (`store/` e `transport/`, decisão 0017)."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from ipm_role.api.domain.access import OrganizationAccess
from ipm_role.api.domain.records import ResourceRecord
from ipm_role.api.domain.role import OwnerQuota, UniqueValue


class Repository(Protocol):
    async def get_role(self, resource_id: str) -> ResourceRecord | None: ...

    async def list_roles(
        self, *, organization_id: str | None, after: str | None, limit: int
    ) -> list[ResourceRecord]:
        """Predefinidas (`core`) e, se `organization_id` vier, as `custom` dessa Organization."""
        ...


class Organizations(Protocol):
    """Projeção local das Organizations, alimentada pelo `DESIRED` (decisão 0100)."""

    def access(self, organization_id: str, subject: str) -> OrganizationAccess: ...


class Users(Protocol):
    """APIs de User e ServiceAccount, para descobrir a Organization do solicitante."""

    async def get_user_organization(self, user_id: str, access_token: str) -> str | None: ...

    async def get_serviceaccount_organization(
        self, serviceaccount_id: str, access_token: str
    ) -> str | None: ...


class RoleUsage(Protocol):
    """APIs de User, Group e ServiceAccount: dizem se uma Role está em uso."""

    async def role_in_use(
        self, organization_id: str, role_name: str, access_token: str
    ) -> bool: ...


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
