"""Rollout do catálogo: as ligações acompanham o catálogo de agora (decisão 0079).

Como o rollout de um Deployment do Kubernetes quando o template muda: na partida do Manager, cada
ligação cujo `desired` difere do que o catálogo atual produz ganha uma geração nova, com uma
Operation `update` do sistema, e o loop aplica a mudança. Quem ligou o serviço antes de uma permissão
nova entrar no catálogo passa a recebê-la, e uma permissão que saiu do catálogo é revogada.

Cada ligação é uma unidade atômica com a linha bloqueada: repetir (outra instância, reinício) não
grava nada de novo, porque o `desired` já é o do catálogo.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from psycopg_pool import AsyncConnectionPool

from sum_service.common.service_rules import rollout_desired
from sum_service.manager.handlers.requested import DESIRED_SUBJECT_PREFIX, desired_envelope
from sum_service.manager.store import ssot

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system:catalog"
"""Quem pede o rollout: o próprio Manager, a partir da configuração (não há usuário)."""


def _now() -> datetime:
    return datetime.now(UTC)


async def roll_out_catalog(
    pool: AsyncConnectionPool[Any],
    catalog: Mapping[str, tuple[str, ...]],
    *,
    clock: Callable[[], datetime] = _now,
) -> int:
    """Grava a geração nova nas ligações que o catálogo mudou. Devolve quantas mudaram."""
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT resource_id FROM sum.service ORDER BY resource_id")
        resource_ids = [str(row[0]) for row in await cursor.fetchall()]
    changed = 0
    for resource_id in resource_ids:
        async with pool.connection() as conn, conn.transaction():
            link = await ssot.link_for_resource(conn, resource_id)
            if link is None:
                continue  # removida entre a lista e a trava
            desired = rollout_desired(link.desired, catalog)
            if desired is None:
                continue
            generation = link.desired_generation + 1
            await ssot.update_link(
                conn, resource_id=resource_id, desired=desired, generation=generation
            )
            operation_id, correlation_id = str(uuid.uuid7()), str(uuid.uuid7())
            await ssot.insert_operation(
                conn,
                operation_id=operation_id,
                resource_id=resource_id,
                operation_type="update",
                desired_generation=generation,
                requested_by=SYSTEM_ACTOR,
                correlation_id=correlation_id,
                request_digest=hashlib.sha256(
                    json.dumps(desired, sort_keys=True).encode()
                ).hexdigest(),
                status="accepted",
                reason=None,
            )
            message_id = str(uuid.uuid7())
            await ssot.insert_outbox(
                conn,
                message_id=message_id,
                resource_id=resource_id,
                subject=f"{DESIRED_SUBJECT_PREFIX}.{resource_id}.changed",
                payload=desired_envelope(
                    message_id=message_id,
                    resource_id=resource_id,
                    generation=generation,
                    desired=desired,
                    requested_by=SYSTEM_ACTOR,
                    correlation_id=correlation_id,
                    causation_id=operation_id,
                    occurred_at=clock(),
                ),
            )
            changed += 1
            logger.info(
                "catalog rolled out to the link",
                extra={
                    "smarkee.resource.id": resource_id,
                    "smarkee.desired.generation": generation,
                    "smarkee.operation.id": operation_id,
                },
            )
    logger.info("catalog rollout finished", extra={"smarkee.links.changed": changed})
    return changed
