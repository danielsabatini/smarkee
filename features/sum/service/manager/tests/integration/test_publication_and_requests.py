"""Testes de integração: publicação do outbox e consumo de `requested` contra o dev.

Variáveis (sem elas, o teste é pulado):
- `SUM_MANAGER_TEST_DATABASE_URL`: papel do Manager (escreve o SSOT e o outbox).
- `SUM_MANAGER_TEST_PUBLISHER_URL`: papel do Publisher (lê o outbox e marca `published_at`).
- `SUM_MANAGER_TEST_MAINTENANCE_URL`: papel de manutenção (lê e limpa o outbox e as Operations).
- `SUM_MANAGER_TEST_NATS_URL`, `SUM_MANAGER_TEST_NATS_USER`, `SUM_MANAGER_TEST_NATS_PASSWORD`:
  broker de dev. Os testes criam um Stream temporário (`TEST_SUM_*`) e o removem; o Stream
  `DESIRED` real não é tocado.

Cada teste limpa o que criou. Operações e mensagens são limpas pelo papel de manutenção.
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
from pydantic import SecretStr

from sum_service_manager.domain.service import parse_catalog
from sum_service_manager.handlers.requested import (
    Recorded,
    RequestedHandler,
    desired_envelope,
)
from sum_service_manager.outbox.publication import PUBLISHED_BY, publish_pending
from sum_service_manager.store import ssot
from sum_service_manager.transport.nats import connect, jetstream_of
from sum_service_manager.transport.publisher import JetStreamPublisher
from sum_service_manager.transport.requested import Disposition, process_request

CATALOG = parse_catalog('{"ipm": ["ipm.organization.get", "ipm.organization.list"]}')
DIGEST = "b" * 64


def _env(name: str) -> str | None:
    return os.environ.get(name)


pytestmark = pytest.mark.skipif(
    _env("SUM_MANAGER_TEST_DATABASE_URL") is None
    or _env("SUM_MANAGER_TEST_PUBLISHER_URL") is None
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
                "specification": {"service": service, "ownerUserId": owner},
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
        await manager.execute("DELETE FROM sum.service WHERE owner_user_id = %s", (owner,))
    finally:
        await maintenance.close()
        await manager.close()


@pytest.fixture
async def writer() -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    connection = await _connect(os.environ["SUM_MANAGER_TEST_DATABASE_URL"])
    yield connection
    await connection.close()


class RecordingPublisher:
    """Publicador de teste: guarda o que sairia para o transporte, sem tocar no NATS."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any], str]] = []

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        envelope: dict[str, Any] = json.loads(payload)
        self.sent.append((subject, envelope, message_id))


async def test_publication_sends_the_real_subject_with_the_envelope_and_marks_it_published(
    writer: psycopg.AsyncConnection[Any],
) -> None:
    owner, operation = _uuid(), _uuid()
    handler = RequestedHandler(catalog=CATALOG)
    outcome = await handler.create(
        writer,
        operation_id=operation,
        request_digest=DIGEST,
        requested_by=owner,
        correlation_id=_uuid(),
        requested_message_id=_uuid(),
        resource_id=_uuid(),
        owner_user_id=owner,
        service="ipm",
    )
    await writer.commit()
    assert isinstance(outcome, Recorded)
    resource_id: str = outcome.resource_id
    publisher_connection = await _connect(
        os.environ["SUM_MANAGER_TEST_PUBLISHER_URL"], autocommit=True
    )
    recorder = RecordingPublisher()
    try:
        published = await publish_pending(publisher_connection, recorder)
        assert published >= 1
        mine = [sent for sent in recorder.sent if sent[1]["resourceId"] == resource_id]
        assert len(mine) == 1
        subject, envelope, message_id = mine[0]
        assert subject == f"manager.desired.sum.service.{resource_id}.changed"
        assert envelope["publishedBy"] == PUBLISHED_BY
        assert envelope["messageId"] == message_id  # `Nats-Msg-Id` = messageId
        assert envelope["data"]["lifecycle"] == "present"
        maintenance = await _connect(os.environ["SUM_MANAGER_TEST_MAINTENANCE_URL"])
        cur = await maintenance.execute(
            "SELECT published_at FROM sum.service_outbox WHERE resource_id = %s", (resource_id,)
        )
        assert (await cur.fetchone())["published_at"] is not None  # type: ignore[index]
        await maintenance.close()
    finally:
        await publisher_connection.close()
        await _cleanup(owner, [resource_id] if resource_id else [])


async def test_the_nats_publisher_deduplicates_by_message_id_on_a_temporary_stream() -> None:
    url = os.environ.get("SUM_MANAGER_TEST_NATS_URL")
    user = os.environ.get("SUM_MANAGER_TEST_NATS_USER")
    password = os.environ.get("SUM_MANAGER_TEST_NATS_PASSWORD")
    if not (url and user and password):
        pytest.skip("broker de dev não configurado para o teste")
    suffix = uuid.uuid4().hex[:8]
    stream = f"TEST_SUM_PUB_{suffix}"
    subject = f"test.sum.service.{suffix}.changed"
    client = await connect(url, user, SecretStr(password), name="sum-service-manager-test")
    jetstream = jetstream_of(client)
    add_stream: Any = cast(Any, jetstream).add_stream
    await add_stream(name=stream, subjects=[subject])
    publisher = JetStreamPublisher(jetstream)
    message_id = _uuid()
    envelope = {"messageId": message_id, "messageType": "desired"}
    try:
        await publisher.publish(subject, json.dumps(envelope).encode(), message_id=message_id)
        await publisher.publish(subject, json.dumps(envelope).encode(), message_id=message_id)
        info = await jetstream.stream_info(stream)
        assert info.state.messages == 1  # a segunda entrega com o mesmo Nats-Msg-Id é descartada
        subscription = await jetstream.pull_subscribe(subject, durable=None)
        (received,) = await subscription.fetch(1, timeout=5)
        assert json.loads(received.data)["messageId"] == message_id
    finally:
        await jetstream.delete_stream(stream)
        await client.close()


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
            "publishedBy": PUBLISHED_BY,
        }
    )
