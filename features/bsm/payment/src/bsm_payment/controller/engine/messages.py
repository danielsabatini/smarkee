"""Montagem das mensagens que o Controller registra no outbox (`desired` suspenso e `updated`).

O Controller não publica: grava no outbox, na mesma transação do estado, e o Publisher publica
(`docs/data/POSTGRESQL.md` §11).
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from bsm_payment.common.contracts import generated
from bsm_payment.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION


def subject_of(message_type: str, resource_id: str) -> str:
    return f"{message_type}.{MODULE}.{RESOURCE_TYPE}.{resource_id}"


class Messages:
    def __init__(self, clock: Callable[[], datetime], identifiers: Callable[[], str]) -> None:
        self._clock = clock
        self._identifiers = identifiers

    def _envelope(
        self,
        message_type: str,
        resource_id: str,
        *,
        requested_by: str | None,
        correlation_id: str | None,
        desired_generation: int | None = None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._clock().isoformat()
        raw: dict[str, Any] = {
            "messageId": self._identifiers(),
            "schemaVersion": SCHEMA_VERSION,
            "messageType": message_type,
            "emitter": "controller",
            "module": MODULE,
            "resourceType": RESOURCE_TYPE,
            "resourceId": resource_id,
            "operation": "changed",
            "occurredAt": now,
            "publishedAt": now,
            "data": data,
        }
        if requested_by is not None:
            raw["requestedBy"] = requested_by
        if correlation_id is not None:
            raw["correlationId"] = correlation_id
        if desired_generation is not None:
            raw["desiredGeneration"] = desired_generation
        envelope = generated.MessageEnvelope.model_validate(raw)
        return envelope.model_dump(mode="json", exclude_none=True)

    def desired(
        self,
        resource_id: str,
        desired: Mapping[str, Any],
        reconciliation: str,
        *,
        generation: int,
        requested_by: str | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        data = generated.PaymentDesiredData.model_validate(
            {**desired, "reconciliation": reconciliation}
        ).model_dump(mode="json", exclude_none=True)
        return self._envelope(
            "desired",
            resource_id,
            requested_by=requested_by,
            correlation_id=correlation_id,
            desired_generation=generation,
            data=data,
        )

    def updated(
        self,
        resource_id: str,
        row: Mapping[str, Any],
        *,
        requested_by: str | None,
        correlation_id: str | None,
        removed: bool = False,
        observed_generation: int | None = None,
    ) -> dict[str, Any]:
        generation = (
            observed_generation
            if observed_generation is not None
            else row.get("observed_generation")
        )
        raw: dict[str, Any] = {
            "phase": row["phase"],
            "lifecycle": "absent" if removed else row["lifecycle"],
            "resourceVersion": str(row["resource_version"]),
            "desiredGeneration": int(row["desired_generation"]),
        }
        if generation is not None:
            raw["observedGeneration"] = int(generation)
        if removed:
            raw["removed"] = True
        data = generated.UpdatedData.model_validate(raw).model_dump(mode="json", exclude_none=True)
        return self._envelope(
            "updated",
            resource_id,
            requested_by=requested_by,
            correlation_id=correlation_id,
            desired_generation=int(row["desired_generation"]),
            data=data,
        )
