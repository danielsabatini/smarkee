"""Testes de integração: `observed` e resultados aplicados ao SSOT de `sum.service` (banco de dev).

Requer `SUM_MANAGER_TEST_DATABASE_URL` (papel do Manager). A linha criada é apagada ao final e a
manutenção limpa o registro de resultados (`SUM_MANAGER_TEST_MAINTENANCE_URL`).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from sum_service.manager.domain.kind import SERVICE
from sum_service.manager.domain.outcome import OutcomeKind
from sum_service.manager.handlers.observed import ObservedHandler
from sum_service.manager.handlers.result import ResultHandler
from sum_service.manager.store.state import StateStore

URL = os.environ.get("SUM_MANAGER_TEST_DATABASE_URL")
MAINTENANCE = os.environ.get("SUM_MANAGER_TEST_MAINTENANCE_URL")
pytestmark = pytest.mark.skipif(
    URL is None or MAINTENANCE is None, reason="URLs de dev não definidas"
)
ROLES = ["ipm.organization.get", "ipm.organization.list"]
T0 = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
APPLIED = OutcomeKind.APPLIED


async def _seed(
    conn: psycopg.AsyncConnection[Any], resource_id: str, owner: str, lifecycle: str
) -> None:
    desired = {
        "lifecycle": lifecycle,
        "reconciliation": "active",
        "ownerAccountId": owner,
        "service": "ipm",
        "serviceRoles": ROLES if lifecycle == "present" else [],
        "managedRoles": ROLES,
    }
    await conn.execute(
        "INSERT INTO sum.service (resource_id, schema_version, owner_account_id, service, "
        "lifecycle, reconciliation, desired, desired_generation, resource_version, phase) "
        "VALUES (%s, '1.0', %s, 'ipm', %s, 'active', %s, 1, 1, 'Pending')",
        (resource_id, owner, lifecycle, Jsonb(desired)),
    )


def observed(
    resource_id: str,
    presence: str,
    roles: list[str],
    *,
    seconds: int,
    generation: int | None = 1,
) -> dict[str, Any]:
    """`generation`: a geração que o Observer conhecia antes de ler o provedor (decisão 0080)."""
    moment = (T0 + timedelta(seconds=seconds)).isoformat()
    return {
        **_envelope(resource_id, "observed", "observer", "changed", moment),
        "presence": presence,
        "observedAt": moment,
        **({"observedGeneration": generation} if generation is not None else {}),
        "data": {"serviceRoles": roles},
    }


def result(resource_id: str, outcome: str, action_id: str, generation: int = 1) -> dict[str, Any]:
    return {
        **_envelope(resource_id, outcome, "executor", "update", T0.isoformat()),
        "actionId": action_id,
        "desiredGeneration": generation,
        "data": {} if outcome == "completed" else {"reason": "Rejected", "retryable": False},
    }


def _envelope(
    resource_id: str, message_type: str, emitter: str, operation: str, moment: str
) -> dict[str, Any]:
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": emitter,
        "module": "sum",
        "resourceType": "service",
        "resourceId": resource_id,
        "operation": operation,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": moment,
        "publishedAt": moment,
    }


async def _observe(conn: psycopg.AsyncConnection[Any], message: dict[str, Any]) -> OutcomeKind:
    return (await ObservedHandler().handle(StateStore(conn), SERVICE, message)).kind


async def _cleanup(resource_id: str) -> None:
    assert MAINTENANCE
    maintenance = await psycopg.AsyncConnection.connect(MAINTENANCE, autocommit=True)
    try:
        for table in ("service_outbox", "service_action_result", "service_operation"):
            await maintenance.execute(
                sql.SQL("DELETE FROM sum.{} WHERE resource_id = %s").format(sql.Identifier(table)),
                (resource_id,),
            )
    finally:
        await maintenance.close()


async def _phase(conn: psycopg.AsyncConnection[Any], resource_id: str) -> tuple[str, int]:
    cursor = await conn.execute(
        "SELECT phase, failure_count FROM sum.service WHERE resource_id = %s", (resource_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    return str(row[0]), int(row[1])


async def _generations(
    conn: psycopg.AsyncConnection[Any], resource_id: str
) -> tuple[int, int | None]:
    cursor = await conn.execute(
        "SELECT desired_generation, observed_generation FROM sum.service WHERE resource_id = %s",
        (resource_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    return int(row[0]), row[1]


async def _outbox_types(conn: psycopg.AsyncConnection[Any], resource_id: str) -> list[str]:
    """Os tipos gravados no outbox, lidos pelo papel de manutenção (o Manager só insere)."""
    assert MAINTENANCE
    maintenance = await psycopg.AsyncConnection.connect(MAINTENANCE, autocommit=True)
    try:
        cursor = await maintenance.execute(
            "SELECT payload->>'messageType' FROM sum.service_outbox WHERE resource_id = %s"
            " ORDER BY sequence",
            (resource_id,),
        )
        return [str(row[0]) for row in await cursor.fetchall()]
    finally:
        await maintenance.close()


async def _operation(
    conn: psycopg.AsyncConnection[Any], resource_id: str, generation: int
) -> tuple[str, str | None]:
    cursor = await conn.execute(
        "SELECT operation_status, completed_at::text FROM sum.service_operation "
        "WHERE resource_id = %s AND desired_generation = %s",
        (resource_id, generation),
    )
    row = await cursor.fetchone()
    assert row is not None
    return str(row[0]), row[1]


async def test_observed_roles_drive_the_phase_and_stale_observations_are_ignored() -> None:
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "present")
        assert await _observe(conn, observed(resource_id, "present", [], seconds=0)) is APPLIED
        assert (await _phase(conn, resource_id))[0] == "Reconciling"
        converged = observed(resource_id, "present", ROLES, seconds=5)
        assert await _observe(conn, converged) is APPLIED
        assert (await _phase(conn, resource_id))[0] == "Ready"
        assert await _generations(conn, resource_id) == (1, 1)
        older = observed(resource_id, "present", [], seconds=1)
        assert await _observe(conn, older) is OutcomeKind.IGNORED
        assert (await _phase(conn, resource_id))[0] == "Ready"
        unknown = observed(resource_id, "unknown", [], seconds=9)
        assert await _observe(conn, unknown) is APPLIED
        assert (await _phase(conn, resource_id))[0] == "Ready"
        assert await _outbox_types(conn, resource_id) == ["updated"] * 3
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        await _cleanup(resource_id)


async def test_a_reading_older_than_the_generation_does_not_confirm_it() -> None:
    """Conteúdo igual não basta: a leitura precisa ser posterior à geração (decisão 0072)."""
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "present")
        stale = observed(resource_id, "present", ROLES, seconds=0, generation=None)
        assert await _observe(conn, stale) is APPLIED
        assert (await _phase(conn, resource_id))[0] == "Reconciling"
        assert await _generations(conn, resource_id) == (1, None)
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        await _cleanup(resource_id)


async def test_a_disabled_link_converges_and_its_record_is_kept() -> None:
    """A ligação desfeita continua existindo (decisão 0033): o Manager não apaga a linha."""
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "absent")
        holding = observed(resource_id, "present", ROLES[:1], seconds=0)
        assert await _observe(conn, holding) is APPLIED
        assert (await _phase(conn, resource_id))[0] == "Reconciling"
        assert await _observe(conn, observed(resource_id, "present", [], seconds=5)) is APPLIED
        assert (await _phase(conn, resource_id))[0] == "Ready"
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        await _cleanup(resource_id)


async def test_failures_are_counted_once_per_action_and_suspend_at_the_limit() -> None:
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    handler = ResultHandler(failure_limit=2)
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "present")
        first = result(resource_id, "failed", f"{resource_id}.1.update.a")
        assert (await handler.handle(StateStore(conn), SERVICE, first)).kind is APPLIED
        assert await _phase(conn, resource_id) == ("Reconciling", 1)
        duplicate = (await handler.handle(StateStore(conn), SERVICE, first)).kind
        assert duplicate is OutcomeKind.DUPLICATE
        assert await _phase(conn, resource_id) == ("Reconciling", 1)
        second = result(resource_id, "failed", f"{resource_id}.1.update.b")
        assert (await handler.handle(StateStore(conn), SERVICE, second)).kind is APPLIED
        assert await _phase(conn, resource_id) == ("Failed", 2)
        cursor = await conn.execute(
            "SELECT reconciliation FROM sum.service WHERE resource_id = %s", (resource_id,)
        )
        assert await cursor.fetchone() == ("suspended",)
        assert "desired" in await _outbox_types(conn, resource_id)  # o Reconciler para
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        await _cleanup(resource_id)


async def test_operations_follow_the_phases_of_the_current_generation() -> None:
    """`Reconciling` marca a Operation como `in_progress`; `Ready` confirmado a conclui."""
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "present")
        await conn.execute(
            "UPDATE sum.service SET desired_generation = 2 WHERE resource_id = %s", (resource_id,)
        )
        for generation in (1, 2):
            await conn.execute(
                "INSERT INTO sum.service_operation (operation_id, resource_id, operation_type, "
                "desired_generation, requested_by, correlation_id, request_digest, "
                "operation_status) "
                "VALUES (%s, %s, 'create', %s, %s, %s, %s, 'accepted')",
                (
                    f"{resource_id}-op-{generation}",
                    resource_id,
                    generation,
                    owner,
                    str(uuid.uuid7()),
                    "0" * 64,
                ),
            )
        pending = observed(resource_id, "present", [], seconds=0, generation=2)
        assert await _observe(conn, pending) is APPLIED
        # A geração 1 foi substituída antes de convergir: `failed`, como nos outros tipos
        # (decisão 0080; o estado próprio `superseded` vem depois).
        status, completed_at = await _operation(conn, resource_id, 1)
        assert status == "failed" and completed_at is not None
        assert await _operation(conn, resource_id, 2) == ("in_progress", None)
        converged = observed(resource_id, "present", ROLES, seconds=5, generation=2)
        assert await _observe(conn, converged) is APPLIED
        status, completed_at = await _operation(conn, resource_id, 2)
        assert status == "completed" and completed_at is not None
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        await _cleanup(resource_id)


async def test_removing_the_account_deletes_only_its_links_and_is_idempotent() -> None:
    assert URL and MAINTENANCE
    from sum_service.manager.handlers.account_removed import remove_links_of

    mine, other = str(uuid.uuid7()), str(uuid.uuid7())
    owner, bystander = str(uuid.uuid7()), str(uuid.uuid7())
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, mine, owner, "absent")
        await _seed(conn, other, bystander, "present")
        assert await remove_links_of(conn, owner) == 1
        assert await remove_links_of(conn, owner) == 0  # repetir não tem efeito
        gone = await conn.execute("SELECT 1 FROM sum.service WHERE resource_id = %s", (mine,))
        kept = await conn.execute("SELECT 1 FROM sum.service WHERE resource_id = %s", (other,))
        assert await gone.fetchone() is None
        assert await kept.fetchone() is not None
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = ANY(%s)", ([mine, other],))
        await conn.close()
