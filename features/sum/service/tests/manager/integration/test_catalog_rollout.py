"""Rollout do catálogo contra o SSOT de dev (decisão 0079).

Usa um serviço só de teste (`zzrollout`): o rollout não toca as ligações de serviços que não estão
no catálogo informado, então as ligações reais do banco de dev ficam como estão. Mesmas variáveis
de `test_consumer.py`; sem elas, o teste é pulado.
"""

import json
import os
import uuid
from typing import Any, cast

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from sum_service.common.service_rules import parse_catalog
from sum_service.manager.handlers.catalog_rollout import SYSTEM_ACTOR, roll_out_catalog
from sum_service.manager.handlers.requested import RequestedHandler
from sum_service.manager.transport.requested import Disposition, process_request

pytestmark = pytest.mark.skipif(
    os.environ.get("SUM_MANAGER_TEST_DATABASE_URL") is None
    or os.environ.get("SUM_MANAGER_TEST_MAINTENANCE_URL") is None,
    reason="URLs dos papéis do banco de dev não definidas",
)

BEFORE = parse_catalog('{"zzrollout": ["zzrollout.a.get", "zzrollout.b.get"]}')
AFTER = parse_catalog('{"zzrollout": ["zzrollout.a.get", "zzrollout.c.get"]}')


def _uuid() -> str:
    return str(uuid.uuid7())


def _create(owner: str, resource_id: str) -> bytes:
    return json.dumps(
        {
            "messageId": _uuid(),
            "schemaVersion": "1.0",
            "messageType": "requested",
            "emitter": "receiver",
            "module": "sum",
            "resourceType": "service",
            "resourceId": resource_id,
            "operation": "create",
            "requestedBy": owner,
            "correlationId": _uuid(),
            "occurredAt": "2026-10-21T14:00:00Z",
            "publishedAt": "2026-10-21T14:00:01Z",
            "publishedBy": "sum-service-receiver",
            "data": {
                "operationId": _uuid(),
                "requestDigest": "c" * 64,
                "specification": {"service": "zzrollout", "ownerAccountId": owner},
            },
        }
    ).encode()


async def _connect(url: str) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(
        url, row_factory=cast(Any, dict_row), autocommit=True
    )


async def test_a_new_catalog_gives_the_links_a_new_generation_with_a_system_operation() -> None:
    owner, resource_id = _uuid(), _uuid()
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        os.environ["SUM_MANAGER_TEST_DATABASE_URL"], min_size=1, max_size=2, open=False
    )
    await pool.open(wait=True)
    maintenance = await _connect(os.environ["SUM_MANAGER_TEST_MAINTENANCE_URL"])
    try:
        message = _create(owner, resource_id)
        assert await process_request(pool, RequestedHandler(catalog=BEFORE), message) is (
            Disposition.ACK
        )
        assert await roll_out_catalog(pool, BEFORE) == 0  # nada mudou: nada gravado

        assert await roll_out_catalog(pool, AFTER) == 1
        async with pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT desired_generation, desired FROM sum.service WHERE resource_id = %s",
                (resource_id,),
            )
            row = await cursor.fetchone()
        assert row is not None and row["desired_generation"] == 2
        assert row["desired"]["serviceRoles"] == ["zzrollout.a.get", "zzrollout.c.get"]
        assert row["desired"]["managedRoles"] == [
            "zzrollout.a.get",
            "zzrollout.b.get",  # saiu do catálogo: continua controlada, para ser revogada
            "zzrollout.c.get",
        ]
        cursor = await maintenance.execute(
            "SELECT operation_type, operation_status, requested_by, desired_generation"
            " FROM sum.service_operation WHERE resource_id = %s ORDER BY created_at",
            (resource_id,),
        )
        operations = await cursor.fetchall()
        assert operations[-1] == {
            "operation_type": "update",
            "operation_status": "accepted",
            "requested_by": SYSTEM_ACTOR,
            "desired_generation": 2,
        }
        cursor = await maintenance.execute(
            "SELECT payload FROM sum.service_outbox WHERE resource_id = %s ORDER BY sequence",
            (resource_id,),
        )
        outbox = await cursor.fetchall()
        assert [item["payload"]["desiredGeneration"] for item in outbox] == [1, 2]
        assert await roll_out_catalog(pool, AFTER) == 0  # repetir não grava de novo
    finally:
        await pool.close()
        for table in ("service_outbox", "service_operation"):
            await maintenance.execute(
                f"DELETE FROM sum.{table} WHERE resource_id = %s",  # noqa: S608 (tabelas fixas)
                (resource_id,),
            )
        await maintenance.close()
        manager = await _connect(os.environ["SUM_MANAGER_TEST_DATABASE_URL"])
        await manager.execute("DELETE FROM sum.service WHERE resource_id = %s", (resource_id,))
        await manager.close()
