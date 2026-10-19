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
from psycopg.types.json import Jsonb

from sum_service.manager.handlers.state import (
    ObservedMessage,
    ResultMessage,
    apply_observed,
    apply_result,
)

URL = os.environ.get("SUM_MANAGER_TEST_DATABASE_URL")
MAINTENANCE = os.environ.get("SUM_MANAGER_TEST_MAINTENANCE_URL")
pytestmark = pytest.mark.skipif(
    URL is None or MAINTENANCE is None, reason="URLs de dev não definidas"
)
ROLES = ["ipm.organization.get", "ipm.organization.list"]
T0 = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)


async def _seed(
    conn: psycopg.AsyncConnection[Any], resource_id: str, owner: str, lifecycle: str
) -> None:
    desired = {
        "lifecycle": lifecycle,
        "reconciliation": "active",
        "ownerAccountId": owner,
        "service": "ipm",
        "serviceRoles": ROLES if lifecycle == "present" else [],
    }
    await conn.execute(
        "INSERT INTO sum.service (resource_id, schema_version, owner_account_id, service, "
        "lifecycle, reconciliation, desired, desired_generation, resource_version, phase) "
        "VALUES (%s, '1.0', %s, 'ipm', %s, 'active', %s, 1, 1, 'Pending')",
        (resource_id, owner, lifecycle, Jsonb(desired)),
    )


async def _phase(conn: psycopg.AsyncConnection[Any], resource_id: str) -> tuple[str, int]:
    cursor = await conn.execute(
        "SELECT phase, failure_count FROM sum.service WHERE resource_id = %s", (resource_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    return str(row[0]), int(row[1])


async def test_observed_roles_drive_the_phase_and_stale_observations_are_ignored() -> None:
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "present")
        missing = ObservedMessage(str(uuid.uuid7()), resource_id, "present", T0, ())
        assert await apply_observed(conn, missing) == "applied"
        assert (await _phase(conn, resource_id))[0] == "Reconciling"
        converged = ObservedMessage(
            str(uuid.uuid7()), resource_id, "present", T0 + timedelta(seconds=5), tuple(ROLES)
        )
        assert await apply_observed(conn, converged) == "applied"
        assert (await _phase(conn, resource_id))[0] == "Ready"
        older = ObservedMessage(
            str(uuid.uuid7()), resource_id, "present", T0 + timedelta(seconds=1), ()
        )
        assert await apply_observed(conn, older) == "stale"
        assert (await _phase(conn, resource_id))[0] == "Ready"
        unknown = ObservedMessage(
            str(uuid.uuid7()), resource_id, "unknown", T0 + timedelta(seconds=9), ()
        )
        assert await apply_observed(conn, unknown) == "applied"
        assert (await _phase(conn, resource_id))[0] == "Ready"
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()


async def test_a_failed_result_marks_the_generation_failed_once_per_action() -> None:
    assert URL and MAINTENANCE
    resource_id, owner = str(uuid.uuid7()), str(uuid.uuid7())
    action_id = f"{resource_id}.1.update.observed"
    conn = await psycopg.AsyncConnection.connect(URL, autocommit=True)
    try:
        await _seed(conn, resource_id, owner, "present")
        failed = ResultMessage(str(uuid.uuid7()), resource_id, action_id, 1, "failed")
        assert await apply_result(conn, failed) == "applied"
        assert await _phase(conn, resource_id) == ("Failed", 1)
        assert await apply_result(conn, failed) == "duplicate"
        assert await _phase(conn, resource_id) == ("Failed", 1)
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        maintenance = await psycopg.AsyncConnection.connect(MAINTENANCE, autocommit=True)
        try:
            await maintenance.execute(
                "DELETE FROM sum.service_action_result WHERE resource_id = %s", (resource_id,)
            )
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


async def test_operations_follow_the_phases_up_to_the_current_generation() -> None:
    """`Reconciling` marca a Operation como `in_progress`; `Ready` a conclui (e as anteriores)."""
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
        pending = ObservedMessage(str(uuid.uuid7()), resource_id, "present", T0, ())
        assert await apply_observed(conn, pending) == "applied"
        assert await _operation(conn, resource_id, 1) == ("in_progress", None)
        assert await _operation(conn, resource_id, 2) == ("in_progress", None)
        converged = ObservedMessage(
            str(uuid.uuid7()), resource_id, "present", T0 + timedelta(seconds=5), tuple(ROLES)
        )
        assert await apply_observed(conn, converged) == "applied"
        for generation in (1, 2):
            status, completed_at = await _operation(conn, resource_id, generation)
            assert status == "completed" and completed_at is not None
    finally:
        await conn.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await conn.close()
        maintenance = await psycopg.AsyncConnection.connect(MAINTENANCE, autocommit=True)
        try:
            await maintenance.execute(
                "DELETE FROM sum.service_operation WHERE resource_id = %s", (resource_id,)
            )
        finally:
            await maintenance.close()


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
