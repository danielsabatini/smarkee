"""Portas que a orquestração exige do SSOT (implementadas por `store/`, decisão 0017)."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from ipm_organization_manager.domain.policy import OwnerQuota, UniqueValue


class Store(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Unidade atômica; levanta `DuplicateWriteError` se duas entregas disputarem a chave."""
        ...

    async def recorded_digest(self, operation_id: str) -> str | None: ...

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool: ...

    async def owned_count(self, quota: OwnerQuota) -> int:
        """Serializa as transações do dono e conta os recursos que ele já tem."""
        ...

    async def insert_resource(
        self, resource_id: str, *, schema_version: str, desired: Mapping[str, Any]
    ) -> None: ...

    async def lock_for_request(self, resource_id: str) -> dict[str, Any] | None: ...

    async def change_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        reconciliation: str,
        phase: str,
        expected_resource_version: int | None,
    ) -> int | None: ...

    async def insert_operation(
        self,
        *,
        operation_id: str,
        resource_id: str,
        operation_type: str,
        generation: int | None,
        requested_by: str,
        correlation_id: str,
        request_digest: str,
        status: str,
        reason: str | None,
        completed_at: Any,
    ) -> None: ...

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None: ...

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None: ...

    async def save_observation(
        self,
        resource_id: str,
        *,
        observed: Mapping[str, Any],
        presence: str,
        observed_at: Any,
        conditions: list[dict[str, Any]],
        phase: str,
    ) -> int: ...

    async def delete_resource(self, resource_id: str) -> None: ...

    async def settle_operations(
        self, resource_id: str, generation: int, *, converged: bool
    ) -> None: ...

    async def set_current_operations(
        self, resource_id: str, generation: int, *, status: str, finished: bool
    ) -> None: ...

    async def record_action_result(
        self, *, action_id: str, resource_id: str, generation: int, outcome: str
    ) -> bool: ...

    async def save_result(
        self,
        resource_id: str,
        *,
        failure_count: int,
        phase: str,
        reconciliation: str,
        conditions: list[dict[str, Any]],
    ) -> int: ...
