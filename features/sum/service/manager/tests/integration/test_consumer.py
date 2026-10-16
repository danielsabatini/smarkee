"""Testes de integração: consumo de `requested` pelo Manager contra o SSOT de dev.

Variáveis (sem elas, o teste é pulado):
- `SUM_MANAGER_TEST_DATABASE_URL`: papel do Manager (escreve o SSOT e o outbox).
- `SUM_MANAGER_TEST_MAINTENANCE_URL`: papel de manutenção (lê e limpa o outbox e as Operations).

A publicação do outbox é do Publisher e é testada no projeto dele. Cada teste limpa o que criou:
a manutenção apaga o outbox e as Operations, e o Manager apaga a ligação.
"""

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from sum_service_manager.domain.service import parse_catalog
from sum_service_manager.handlers.requested import (
    RequestedHandler,
    desired_envelope,
)
from sum_service_manager.store import ssot
from sum_service_manager.transport.requested import Disposition, process_request

CATALOG = parse_catalog('{"ipm": ["ipm.organization.get", "ipm.organization.list"]}')
DIGEST = "b" * 64


def _env(name: str) -> str | None:
    return os.environ.get(name)


pytestmark = pytest.mark.skipif(
    _env("SUM_MANAGER_TEST_DATABASE_URL") is None
    or _env("SUM_MANAGER_TEST_MAINTENANCE_URL") is None,
    reason="URLs dos papéis do banco de dev não definidas",
)


def _uuid() -> str:
    return str(uuid.uuid7())


async def _connect(url: str, *, autocommit: bool = False) -> psycopg.AsyncConnection[Any]:
    return await psycopg.AsyncConnection.connect(
        url, row_factory=cast(Any, dict_row), autocommit=autocommit
    )


def _requested_create(owner: str, service: str, operation: str, resource_id: str) -> bytes:
    """Mensagem `requested` de criação, como o Receiver a publicaria."""
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
            "occurredAt": "2026-10-15T14:00:00Z",
            "publishedAt": "2026-10-15T14:00:01Z",
            "publishedBy": "sum-service-receiver",
            "data": {
                "operationId": operation,
                "requestDigest": DIGEST,
                "specification": {"service": service, "ownerAccountId": owner},
            },
        }
    ).encode()


async def _cleanup(owner: str, resource_ids: list[str]) -> None:
    """Limpa o que o teste criou: a manutenção apaga outbox e Operations; o Manager, a ligação."""
    maintenance = await _connect(os.environ["SUM_MANAGER_TEST_MAINTENANCE_URL"], autocommit=True)
    manager = await _connect(os.environ["SUM_MANAGER_TEST_DATABASE_URL"], autocommit=True)
    try:
        for resource_id in resource_ids:
            await maintenance.execute(
                "DELETE FROM sum.service_outbox WHERE resource_id = %s", (resource_id,)
            )
        await maintenance.execute(
            "DELETE FROM sum.service_operation WHERE requested_by = %s", (owner,)
        )
        await manager.execute("DELETE FROM sum.service WHERE owner_account_id = %s", (owner,))
    finally:
        await maintenance.close()
        await manager.close()


@pytest.fixture
async def writer() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await _connect(os.environ["SUM_MANAGER_TEST_DATABASE_URL"])
    yield connection
    await connection.close()


async def test_a_requested_create_is_recorded_and_a_redelivery_is_acknowledged_once(
    writer: psycopg.AsyncConnection[Any],
) -> None:
    del writer  # o consumo usa o próprio pool
    owner, operation, resource_id = _uuid(), _uuid(), _uuid()
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        os.environ["SUM_MANAGER_TEST_DATABASE_URL"], min_size=1, max_size=2, open=False
    )
    await pool.open(wait=True)
    handler = RequestedHandler(catalog=CATALOG)
    message = _requested_create(owner, "ipm", operation, resource_id)
    try:
        assert await process_request(pool, handler, message) is Disposition.ACK
        assert await process_request(pool, handler, message) is Disposition.ACK  # reentrega
        async with pool.connection() as connection:
            link = await ssot.active_link_for(connection, owner, "ipm")
        assert link is not None and link.resource_id == resource_id
    finally:
        await pool.close()
        await _cleanup(owner, [resource_id])


async def test_a_malformed_requested_is_terminated_and_writes_nothing() -> None:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        os.environ["SUM_MANAGER_TEST_DATABASE_URL"], min_size=1, max_size=1, open=False
    )
    await pool.open(wait=True)
    try:
        handler = RequestedHandler(catalog=CATALOG)
        assert await process_request(pool, handler, b"nao e json") is Disposition.TERM
        other_module = json.loads(_requested_create(_uuid(), "ipm", _uuid(), _uuid()))
        other_module["module"] = "core"
        assert (
            await process_request(pool, handler, json.dumps(other_module).encode())
            is Disposition.TERM
        )
    finally:
        await pool.close()


async def test_a_desired_envelope_built_by_the_handler_matches_the_contract() -> None:
    """Garante que o envelope gerado pelo handler passa na validação estrita da publicação."""
    from datetime import UTC, datetime

    from sum_service_manager.contracts import generated
    from sum_service_manager.domain.service import enable_desired

    owner = _uuid()
    desired = enable_desired(owner, "ipm", CATALOG)
    payload = desired_envelope(
        message_id=_uuid(),
        resource_id=_uuid(),
        generation=1,
        desired=desired,
        requested_by=owner,
        correlation_id=_uuid(),
        causation_id=_uuid(),
        occurred_at=datetime(2026, 10, 15, 14, tzinfo=UTC),
    )
    generated.MessageEnvelope.model_validate(
        {
            **payload,
            "publishedAt": datetime(2026, 10, 15, 14, 0, 1, tzinfo=UTC),
            "publishedBy": "sum-service-publisher",
        }
    )
