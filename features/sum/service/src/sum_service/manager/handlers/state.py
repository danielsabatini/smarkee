"""Aplicação de `observed` e de resultados ao SSOT de `sum.service` (decisão 0033).

Cada mensagem é uma unidade atômica: a linha da ligação é bloqueada antes de decidir. Um `observed`
mais antigo que o último aplicado é ignorado. Um resultado já registrado (mesmo `actionId`) não é
contado de novo.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from sum_service.manager.domain.convergence import phase_after_observation


@dataclass(frozen=True, slots=True)
class ObservedMessage:
    message_id: str
    resource_id: str
    presence: str
    observed_at: datetime
    service_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResultMessage:
    message_id: str
    resource_id: str
    action_id: str
    desired_generation: int
    outcome: str
    """`completed` ou `failed`."""


async def apply_observed(conn: AsyncConnection[Any], message: ObservedMessage) -> str:
    """Grava a observação e a fase.

    Devolve `applied`, `stale` (mais antiga que a última aplicada) ou `unknown_resource`.
    """
    async with conn.cursor() as cursor:
        await cursor.execute(
            "SELECT lifecycle, desired, observed_at FROM sum.service "
            "WHERE resource_id = %s FOR UPDATE",
            (message.resource_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return "unknown_resource"
    lifecycle, desired, last_observed_at = row[0], row[1], row[2]
    if last_observed_at is not None and message.observed_at <= last_observed_at:
        return "stale"
    phase = phase_after_observation(
        lifecycle=str(lifecycle),
        desired_roles=_roles(desired.get("serviceRoles", [])),
        presence=message.presence,
        observed_roles=message.service_roles,
    )
    if phase is None:
        await conn.execute(
            "UPDATE sum.service SET presence = 'unknown', observed_at = %s, updated_at = now() "
            "WHERE resource_id = %s",
            (message.observed_at, message.resource_id),
        )
        return "applied"
    await conn.execute(
        "UPDATE sum.service SET observed = %s, presence = %s, observed_at = %s, phase = %s, "
        "updated_at = now() WHERE resource_id = %s",
        (
            Jsonb({"serviceRoles": list(message.service_roles)}),
            message.presence,
            message.observed_at,
            phase,
            message.resource_id,
        ),
    )
    await _advance_operations(conn, message.resource_id, phase)
    return "applied"


async def _advance_operations(conn: AsyncConnection[Any], resource_id: str, phase: str) -> None:
    """Acompanha as Operations até a geração atual (`docs/SSOT.md`, `operation_status`).

    `Reconciling` marca as pendentes como `in_progress`; `Ready` as conclui. Uma Operation de
    geração anterior à atual também é concluída: o `Ready` da geração atual já a cobre.
    """
    if phase == "Ready":
        await conn.execute(
            "UPDATE sum.service_operation "
            "SET operation_status = 'completed', completed_at = now(), updated_at = now() "
            "WHERE resource_id = %s AND operation_status IN ('accepted', 'in_progress') "
            "AND desired_generation <= "
            "(SELECT desired_generation FROM sum.service WHERE resource_id = %s)",
            (resource_id, resource_id),
        )
    elif phase == "Reconciling":
        await conn.execute(
            "UPDATE sum.service_operation "
            "SET operation_status = 'in_progress', updated_at = now() "
            "WHERE resource_id = %s AND operation_status = 'accepted' "
            "AND desired_generation <= "
            "(SELECT desired_generation FROM sum.service WHERE resource_id = %s)",
            (resource_id, resource_id),
        )


async def apply_result(conn: AsyncConnection[Any], message: ResultMessage) -> str:
    """Registra o resultado, uma vez por `actionId`.

    Falha marca a fase `Failed` na geração da ação.
    """
    async with conn.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO sum.service_action_result "
            "(action_id, resource_id, desired_generation, action_outcome) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (action_id) DO NOTHING RETURNING action_id",
            (
                message.action_id,
                message.resource_id,
                message.desired_generation,
                message.outcome,
            ),
        )
        inserted = await cursor.fetchone()
    if inserted is None:
        return "duplicate"
    if message.outcome == "failed":
        await conn.execute(
            "UPDATE sum.service SET phase = 'Failed', failure_count = failure_count + 1, "
            "updated_at = now() WHERE resource_id = %s AND desired_generation = %s",
            (message.resource_id, message.desired_generation),
        )
    return "applied"


def _roles(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = cast("list[object]", value)
    return tuple(str(role) for role in items)
