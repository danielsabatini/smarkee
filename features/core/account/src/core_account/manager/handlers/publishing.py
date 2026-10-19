"""Montagem das mensagens que o Manager registra no outbox (`desired` e `updated`).

O Manager não publica: grava no outbox, na mesma transação, e o Publisher publica
(`docs/POSTGRESQL.md` §11).
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from core_account.common.contracts import generated
from core_account.common.resource import MODULE, SCHEMA_VERSION
from core_account.manager.domain.kind import ResourceKind
from core_account.manager.handlers.envelope import require
from core_account.manager.handlers.ports import Store


def subject_of(kind: ResourceKind, message_type: str, resource_id: str) -> str:
    return f"manager.{message_type}.{MODULE}.{kind.resource_type}.{resource_id}.changed"


class Publishing:
    def __init__(self, clock: Callable[[], datetime], identifiers: Callable[[], str]) -> None:
        self._clock = clock
        self._identifiers = identifiers

    async def desired(
        self,
        store: Store,
        kind: ResourceKind,
        cause: generated.MessageEnvelope,
        *,
        desired: Mapping[str, Any],
        reconciliation: str,
        generation: int,
    ) -> None:
        now = self._clock()
        message = generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "desired",
                "emitter": "manager",
                "module": MODULE,
                "resourceType": kind.resource_type,
                "resourceId": cause.resource_id,
                "operation": "changed",
                "desiredGeneration": generation,
                "requestedBy": require(cause.requested_by),
                "correlationId": require(cause.correlation_id),
                "causationId": cause.message_id,
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": kind.policy.message_data(desired, reconciliation),
            }
        ).model_dump(mode="json", exclude_none=True)
        await store.add_to_outbox(
            message,
            resource_id=cause.resource_id,
            subject=subject_of(kind, "desired", cause.resource_id),
        )

    async def suspended_desired(
        self,
        store: Store,
        kind: ResourceKind,
        cause: generated.MessageEnvelope,
        *,
        desired: Mapping[str, Any],
        generation: int,
    ) -> None:
        """`desired` com a reconciliação suspensa, publicado ao atingir o limite de falhas."""
        now = self._clock()
        message = generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "desired",
                "emitter": "manager",
                "module": MODULE,
                "resourceType": kind.resource_type,
                "resourceId": cause.resource_id,
                "operation": "changed",
                "desiredGeneration": generation,
                **({"requestedBy": cause.requested_by} if cause.requested_by else {}),
                "correlationId": cause.correlation_id or self._identifiers(),
                "causationId": cause.message_id,
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": kind.policy.message_data(desired, "suspended"),
            }
        ).model_dump(mode="json", exclude_none=True)
        await store.add_to_outbox(
            message,
            resource_id=cause.resource_id,
            subject=subject_of(kind, "desired", cause.resource_id),
        )

    async def updated(
        self,
        store: Store,
        kind: ResourceKind,
        cause: generated.MessageEnvelope,
        *,
        lifecycle: str,
        phase: str,
        resource_version: int,
        removed: bool = False,
    ) -> None:
        now = self._clock()
        message = generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": "updated",
                "emitter": "manager",
                "module": MODULE,
                "resourceType": kind.resource_type,
                "resourceId": cause.resource_id,
                "operation": "changed",
                "correlationId": cause.correlation_id or self._identifiers(),
                "causationId": cause.message_id,
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": {
                    "phase": phase,
                    "lifecycle": lifecycle,
                    "resourceVersion": str(resource_version),
                    **({"removed": True} if removed else {}),
                },
            }
        ).model_dump(mode="json", exclude_none=True)
        await store.add_to_outbox(
            message,
            resource_id=cause.resource_id,
            subject=subject_of(kind, "updated", cause.resource_id),
        )
