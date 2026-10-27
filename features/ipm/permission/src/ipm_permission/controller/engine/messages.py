"""Montagem das mensagens que o Controller registra no outbox (`desired` suspenso e `updated`).

O Controller não publica: grava no outbox, na mesma transação do estado, e o Publisher publica
(`docs/data/POSTGRESQL.md` §11). O contrato e o `emitter` (`manager`, dono do SSOT do tipo) são os
do Manager antes da decisão 0096: os consumidores do `updated` não mudam.
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from ipm_permission.common.contracts import generated
from ipm_permission.common.resource import MODULE, RESOURCE_TYPE, SCHEMA_VERSION


def subject_of(message_type: str, resource_id: str) -> str:
    return f"manager.{message_type}.{MODULE}.{RESOURCE_TYPE}.{resource_id}.changed"


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
        data: Mapping[str, Any],
        desired_generation: int | None = None,
    ) -> dict[str, Any]:
        now = self._clock()
        return generated.MessageEnvelope.model_validate(
            {
                "messageId": self._identifiers(),
                "schemaVersion": SCHEMA_VERSION,
                "messageType": message_type,
                "emitter": "manager",
                "module": MODULE,
                "resourceType": RESOURCE_TYPE,
                "resourceId": resource_id,
                "operation": "changed",
                **({"desiredGeneration": desired_generation} if desired_generation else {}),
                **({"requestedBy": requested_by} if requested_by else {}),
                "correlationId": correlation_id or self._identifiers(),
                "occurredAt": now.isoformat(),
                "publishedAt": now.isoformat(),
                "data": dict(data),
            }
        ).model_dump(mode="json", exclude_none=True)

    def suspended_desired(
        self,
        resource_id: str,
        *,
        desired: Mapping[str, Any],
        generation: int,
        requested_by: str | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        """`desired` com a reconciliação suspensa, publicado ao atingir o limite de falhas."""
        data = generated.PermissionDesiredData.model_validate(
            {
                "lifecycle": desired["lifecycle"],
                "reconciliation": "suspended",
                "name": desired["name"],
                "description": desired["description"],
                "grantable": bool(desired.get("grantable", False)),
                "deletionProtection": desired.get("deletionProtection", True) is not False,
            }
        ).model_dump(mode="json", by_alias=True, exclude_none=True)
        return self._envelope(
            "desired",
            resource_id,
            requested_by=requested_by,
            correlation_id=correlation_id,
            data=data,
            desired_generation=generation,
        )

    def updated(
        self,
        resource_id: str,
        *,
        lifecycle: str,
        phase: str,
        resource_version: int,
        desired_generation: int,
        observed_generation: int | None,
        correlation_id: str | None,
        removed: bool = False,
    ) -> dict[str, Any]:
        """`updated` com o par de gerações (semântica do Kubernetes).

        `observedGeneration` igual a `desiredGeneration`, com a fase `Ready`, indica que a última
        alteração terminou; menor, que ainda está em andamento.
        """
        data: dict[str, Any] = {
            "phase": phase,
            "lifecycle": lifecycle,
            "resourceVersion": str(resource_version),
            "desiredGeneration": desired_generation,
        }
        if observed_generation is not None:
            data["observedGeneration"] = observed_generation
        if removed:
            data["removed"] = True
        return self._envelope(
            "updated",
            resource_id,
            requested_by=None,
            correlation_id=correlation_id,
            data=data,
        )
