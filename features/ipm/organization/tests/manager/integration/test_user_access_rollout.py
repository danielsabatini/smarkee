"""Rollout do `userAccess` contra o SSOT de dev (decisão 0081).

O rollout recebe só as Organizations do teste (`only`): as de verdade do banco de dev ficam como
estão. Requer a stack de dev no ar (veja `conftest.py`); sem o banco, o teste é pulado.
"""

import uuid
from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool
from support_manager import Cleanup, dsn, fetch_all, requested_message, ssot, unique_suffix

from ipm_organization.common.user_access import desired_user_access
from ipm_organization.manager.domain.kind import ORGANIZATION, organization_kind
from ipm_organization.manager.domain.outcome import OutcomeKind
from ipm_organization.manager.handlers.requested import RequestedHandler
from ipm_organization.manager.handlers.user_access_rollout import (
    SYSTEM_ACTOR,
    roll_out_user_access,
)

Connection = psycopg.AsyncConnection[Any]
USER_ACCESS = desired_user_access(
    user_executor_account_id="rollout-executor", user_observer_account_id="rollout-observer"
)


async def test_an_organization_from_before_0081_gets_the_user_access_once(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    resource_id = cleanup.track(str(uuid.uuid7()))
    created = requested_message(
        resource_type="organization",
        resource_id=resource_id,
        operation="create",
        requested_by="user-1",
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": "0" * 64,
            "specification": {"name": f"org-{unique_suffix()}", "platformAccess": "granted"},
        },
    )
    # Criada sem `userAccess`, como antes da decisão 0081.
    outcome = await RequestedHandler().handle(ssot(organization_manager), ORGANIZATION, created)
    assert outcome.kind is OutcomeKind.ACCEPTED

    kind = organization_kind(USER_ACCESS)
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        dsn("ipm_organization_manager_login"), min_size=1, max_size=2, open=False
    )
    await pool.open()
    try:
        assert await roll_out_user_access(pool, kind, only={resource_id}) == 1
        assert await roll_out_user_access(pool, kind, only={resource_id}) == 0  # idempotente
    finally:
        await pool.close()

    rows = await fetch_all(
        organization_manager,
        "SELECT desired_generation, desired, phase FROM ipm.organization WHERE resource_id = %s",
        resource_id,
    )
    assert (rows[0]["desired_generation"], rows[0]["phase"]) == (2, "Reconciling")
    assert rows[0]["desired"]["userAccess"] == USER_ACCESS
    operations = await fetch_all(
        organization_manager,
        "SELECT operation_type, desired_generation, requested_by, operation_status"
        " FROM ipm.organization_operation WHERE resource_id = %s ORDER BY desired_generation",
        resource_id,
    )
    assert [tuple(item.values()) for item in operations] == [
        ("create", 1, "user-1", "accepted"),
        ("update", 2, SYSTEM_ACTOR, "accepted"),
    ]
    published = await fetch_all(
        outbox_reader,
        "SELECT payload FROM ipm.organization_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )
    assert len(published) == 2
    latest = published[-1]["payload"]
    assert (latest["desiredGeneration"], latest["requestedBy"]) == (2, SYSTEM_ACTOR)
    assert latest["data"]["userAccess"] == USER_ACCESS
