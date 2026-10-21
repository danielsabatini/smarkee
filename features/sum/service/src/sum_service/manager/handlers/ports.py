"""Porta do SSOT que os handlers do template exigem (implementada em `store/state.py`)."""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol


class Store(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Unidade atômica; levanta `DuplicateWriteError` se duas entregas disputarem a chave."""
        ...

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
        observed_generation: int | None,
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
