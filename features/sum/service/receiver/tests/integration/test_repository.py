"""Teste de integração do repositório de leitura do Receiver contra o banco de dev.

Requer `SUM_SERVICE_RECEIVER_TEST_DATABASE_URL` (papel `sum_service_receiver_login`) e
`SUM_SERVICE_RECEIVER_TEST_MANAGER_URL` (papel `sum_service_manager_login`, que grava e apaga a
linha de teste). Sem as variáveis, o teste é pulado.
"""

import os
import uuid
from typing import Any, cast

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from sum_service_receiver.store.repository import Repository

READER = os.environ.get("SUM_SERVICE_RECEIVER_TEST_DATABASE_URL")
WRITER = os.environ.get("SUM_SERVICE_RECEIVER_TEST_MANAGER_URL")
pytestmark = pytest.mark.skipif(
    READER is None or WRITER is None,
    reason="URLs dos papéis de dev não definidas",
)


async def test_the_repository_reads_links_by_owner_and_service_from_the_views() -> None:
    assert READER and WRITER
    owner, resource_id = str(uuid.uuid7()), str(uuid.uuid7())
    desired = {
        "lifecycle": "present",
        "reconciliation": "active",
        "ownerUserId": owner,
        "service": "ipm",
        "serviceRoles": ["ipm.organization.get"],
    }
    writer = await psycopg.AsyncConnection.connect(WRITER, autocommit=True)
    try:
        await writer.execute(
            "INSERT INTO sum.service (resource_id, schema_version, owner_user_id, service, "
            "lifecycle, "
            "reconciliation, desired, desired_generation, resource_version, phase) "
            "VALUES (%s, '1.0', %s, 'ipm', 'present', 'active', %s, 1, 1, 'Pending')",
            (resource_id, owner, Jsonb(desired)),
        )
    finally:
        await writer.close()
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        READER,
        min_size=1,
        max_size=1,
        kwargs={"autocommit": True, "row_factory": cast(Any, dict_row)},
        open=False,
    )
    await pool.open(wait=True)
    try:
        repository = Repository(pool)
        assert await repository.active_link_for(owner, "ipm") == resource_id
        assert await repository.active_link_for(owner, "sum") is None
        found = await repository.link(resource_id)
        assert found is not None and found["desired"]["service"] == "ipm"
        assert [row["resource_id"] for row in await repository.links_of(owner)] == [resource_id]
    finally:
        await pool.close()
        # A ligação é do Manager: só ele tem DELETE em `sum.service`.
        manager = await psycopg.AsyncConnection.connect(WRITER, autocommit=True)
        try:
            await manager.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        finally:
            await manager.close()
