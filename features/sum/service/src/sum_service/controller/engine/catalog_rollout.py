"""Rollout do catálogo: as ligações acompanham o catálogo de agora (decisão 0079).

Como o rollout de um Deployment do Kubernetes quando o template muda: na partida do Controller,
cada ligação cujo `desired` difere do que o catálogo atual produz ganha uma geração nova, e o loop
aplica a mudança. Quem ligou o serviço antes de uma permissão nova entrar no catálogo passa a
recebê-la, e a que saiu é revogada.

Cada ligação é uma unidade atômica com a linha bloqueada: repetir (outra instância, reinício) não
grava nada de novo, porque o `desired` já é o do catálogo.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from psycopg_pool import AsyncConnectionPool

from sum_service.common.ids import new_identifier, utc_now
from sum_service.common.service_rules import rollout_desired
from sum_service.controller.engine.messages import Messages, subject_of
from sum_service.controller.store.ssot import ControllerSsotStore

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system:catalog"
"""Quem pede o rollout: o próprio Controller, a partir da configuração (não há usuário)."""


async def roll_out_catalog(
    pool: AsyncConnectionPool[Any],
    catalog: Mapping[str, tuple[str, ...]],
    *,
    clock: Callable[[], datetime] = utc_now,
    identifiers: Callable[[], str] = new_identifier,
) -> int:
    """Grava a geração nova nas ligações que o catálogo mudou. Devolve quantas mudaram."""
    async with pool.connection() as connection:
        resource_ids = await ControllerSsotStore(connection).resource_ids()
    changed = 0
    messages = Messages(clock, identifiers)
    for resource_id in resource_ids:
        async with pool.connection() as connection:
            store = ControllerSsotStore(connection)
            async with store.transaction():
                row = await store.lock_resource(resource_id)
                if row is None:
                    continue  # removida entre a lista e a trava
                desired = rollout_desired(row["desired"], catalog)
                if desired is None:
                    continue
                generation = int(row["desired_generation"]) + 1
                correlation_id = identifiers()
                await store.change_desired(
                    resource_id,
                    desired=desired,
                    generation=generation,
                    requested_by=SYSTEM_ACTOR,
                    correlation_id=correlation_id,
                )
                message = messages.desired(
                    resource_id,
                    desired=desired,
                    generation=generation,
                    requested_by=SYSTEM_ACTOR,
                    correlation_id=correlation_id,
                )
                await store.add_to_outbox(
                    message, resource_id=resource_id, subject=subject_of("desired", resource_id)
                )
        changed += 1
        logger.info(
            "catalog rolled out to the link",
            extra={"smarkee.resource.id": resource_id, "smarkee.desired.generation": generation},
        )
    logger.info("catalog rollout finished", extra={"smarkee.links.changed": changed})
    return changed
