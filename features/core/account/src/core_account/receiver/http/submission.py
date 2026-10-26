"""Publicação do `requested` pelo Receiver: identidade da Operation, idempotência e envio.

Cada escrita da API termina aqui: gera a Operation, evita republicar um pedido repetido com a mesma
`Idempotency-Key` e publica o `requested` (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1).
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from http import HTTPStatus
from typing import Any, Protocol

from core_account.common.contracts import generated
from core_account.common.logging_config import bind_context
from core_account.common.ports import Publisher, PublishError
from core_account.common.resource import MODULE, RESOURCE_TYPE
from core_account.receiver.domain.errors import ApiError
from core_account.receiver.domain.records import OperationRecord
from core_account.receiver.domain.requests import operation_id_for, request_digest

logger = logging.getLogger(__name__)


class OperationFinder(Protocol):
    async def find_operation(self, operation_id: str) -> OperationRecord | None: ...


class SubmissionPorts(Protocol):
    """O que a publicação precisa das dependências do Receiver (cada feature as monta)."""

    @property
    def repository(self) -> OperationFinder: ...

    @property
    def publisher(self) -> Publisher: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...

    @property
    def identifiers(self) -> Callable[[], str]: ...


async def submit(
    deps: SubmissionPorts,
    *,
    resource_id: str,
    operation: str,
    requested_by: str,
    digest_content: dict[str, Any],
    extra_data: dict[str, Any],
    idempotency_key: str | None,
    log_context: Mapping[str, str] | None = None,
) -> generated.ApiAcceptedResponse:
    """Gera a identidade da Operation, evita republicar e publica o `requested`.

    `log_context` acrescenta ao contexto de log campos próprios do tipo (por exemplo, o dono).
    """
    bind_context(
        requested_by=requested_by,
        resource_id=resource_id,
        operation=operation,
        **(log_context or {}),
    )
    operation_id = operation_id_for(
        module=MODULE,
        resource_type=RESOURCE_TYPE,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
    )
    digest = request_digest(digest_content)
    if idempotency_key is not None:
        existing = await deps.repository.find_operation(operation_id)
        if existing is not None:
            if existing.request_digest != digest:
                raise ApiError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "IdempotencyKeyReused",
                    "A Idempotency-Key já foi usada com outro conteúdo.",
                )
            return generated.ApiAcceptedResponse.model_validate(
                {"resourceId": existing.resource_id, "operationId": existing.operation_id}
            )
    now = deps.clock()
    message_id = deps.identifiers()
    envelope = generated.MessageEnvelope.model_validate(
        {
            "messageId": message_id,
            "schemaVersion": "1.0",
            "messageType": "requested",
            "emitter": "receiver",
            "module": MODULE,
            "resourceType": RESOURCE_TYPE,
            "resourceId": resource_id,
            "operation": operation,
            "requestedBy": requested_by,
            "correlationId": deps.identifiers(),
            "occurredAt": now.isoformat(),
            "publishedAt": now.isoformat(),
            "data": {"operationId": operation_id, "requestDigest": digest, **extra_data},
        }
    )
    subject = f"receiver.requested.{MODULE}.{RESOURCE_TYPE}.{resource_id}.{operation}"
    try:
        await deps.publisher.publish(
            subject, envelope.model_dump_json(exclude_none=True).encode(), message_id=message_id
        )
    except PublishError:
        raise ApiError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "ServiceUnavailable",
            "Não foi possível registrar o pedido agora. Tente novamente.",
            headers={"Retry-After": "5"},
        ) from None
    logger.info(
        "request published",
        extra={
            "smarkee.resource.id": resource_id,
            "smarkee.operation.name": operation,
            "smarkee.outcome": "accepted",
        },
    )
    return generated.ApiAcceptedResponse.model_validate(
        {"resourceId": resource_id, "operationId": operation_id}
    )
