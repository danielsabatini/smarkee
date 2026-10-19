"""Testes de integração do Publisher de `sum.service` contra o banco e o NATS de dev.

Variáveis (sem elas, o teste é pulado): `SUM_SERVICE_PUBLISHER_TEST_URL` (papel do Publisher),
`SUM_SERVICE_PUBLISHER_TEST_MANAGER_URL` (papel do Manager, só para gravar a linha do outbox),
`SUM_SERVICE_PUBLISHER_TEST_MAINTENANCE_URL` (limpeza e leitura de `published_at`), e
`SUM_SERVICE_PUBLISHER_TEST_NATS_*` para o messaging. O teste usa um Stream temporário e não toca no
`DESIRED` real.
"""

import json
import os
import uuid
from typing import Any, cast

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from sum_service.common.messaging import StreamPublisher, connect, stream_of
from sum_service.common.ports import PublishError
from sum_service.common.settings import MessagingSettings
from sum_service.publisher.outbox.publication import publish_pending

REQUIRED = (
    "SUM_SERVICE_PUBLISHER_TEST_URL",
    "SUM_SERVICE_PUBLISHER_TEST_MANAGER_URL",
    "SUM_SERVICE_PUBLISHER_TEST_MAINTENANCE_URL",
)
pytestmark = pytest.mark.skipif(
    any(os.environ.get(name) is None for name in REQUIRED),
    reason="URLs dos papéis de dev não definidas",
)

ENVELOPE_FIELDS: dict[str, Any] = {
    "schemaVersion": "1.0",
    "messageType": "desired",
    "emitter": "manager",
    "module": "sum",
    "resourceType": "service",
    "operation": "changed",
    "desiredGeneration": 1,
    "requestedBy": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "correlationId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1d",
    "causationId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1e",
    "occurredAt": "2026-10-15T14:00:00Z",
    "data": {
        "lifecycle": "present",
        "reconciliation": "active",
        "ownerAccountId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
        "service": "ipm",
        "serviceRoles": ["ipm.organization.get"],
    },
}


def _uuid() -> str:
    return str(uuid.uuid7())


async def _insert_outbox(
    subject: str, resource_id: str, message_id: str, payload: dict[str, Any]
) -> None:
    """Grava a linha como o Manager faria (papel do Manager), e confirma."""
    manager = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_MANAGER_URL"]
    )
    try:
        await manager.execute(
            "INSERT INTO sum.service_outbox (message_id, resource_id, subject, payload) "
            "VALUES (%s, %s, %s, %s)",
            (message_id, resource_id, subject, Jsonb(payload)),
        )
        await manager.commit()
    finally:
        await manager.close()


async def _published_at(resource_id: str) -> Any:
    maintenance = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_MAINTENANCE_URL"], row_factory=cast(Any, dict_row)
    )
    try:
        cur = await maintenance.execute(
            "SELECT published_at FROM sum.service_outbox WHERE resource_id = %s", (resource_id,)
        )
        row = cast(dict[str, Any] | None, await cur.fetchone())
        return None if row is None else row["published_at"]
    finally:
        await maintenance.close()


async def _cleanup(resource_id: str) -> None:
    maintenance = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_MAINTENANCE_URL"], autocommit=True
    )
    try:
        await maintenance.execute(
            "DELETE FROM sum.service_outbox WHERE resource_id = %s", (resource_id,)
        )
    finally:
        await maintenance.close()


class RefusingPublisher:
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        raise PublishError("MaxPayloadError", permanent=True)


async def test_an_invalid_outbox_message_stops_the_batch_and_stays_pending() -> None:
    resource_id = _uuid()
    await _insert_outbox(
        f"test.sum.service.{resource_id}.changed", resource_id, _uuid(), {"messageType": "x"}
    )
    connection = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_URL"], autocommit=True
    )
    try:
        result = await publish_pending(connection, RefusingPublisher())
        # Mensagem fora do envelope: falha permanente, o lote para e a mensagem fica pendente.
        assert (result.failed, result.permanent_failure, result.published) == (True, True, 0)
        assert await _published_at(resource_id) is None
    finally:
        await connection.close()
        await _cleanup(resource_id)


async def test_a_permanent_refusal_from_the_transport_keeps_the_message_pending() -> None:
    resource_id = _uuid()
    payload = {**ENVELOPE_FIELDS, "messageId": _uuid(), "resourceId": resource_id}
    await _insert_outbox(
        f"test.sum.service.{resource_id}.changed", resource_id, payload["messageId"], payload
    )
    connection = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_URL"], autocommit=True
    )
    try:
        result = await publish_pending(connection, RefusingPublisher())
        assert (result.failed, result.permanent_failure, result.published) == (True, True, 0)
        assert await _published_at(resource_id) is None
    finally:
        await connection.close()
        await _cleanup(resource_id)


async def test_a_valid_message_is_published_once_on_a_temporary_stream_and_marked() -> None:
    url = os.environ.get("SUM_SERVICE_PUBLISHER_TEST_NATS_URL")
    user = os.environ.get("SUM_SERVICE_PUBLISHER_TEST_NATS_USER")
    password = os.environ.get("SUM_SERVICE_PUBLISHER_TEST_NATS_PASSWORD")
    if not (url and user and password):
        pytest.skip("messaging de dev não configurado para o teste")
    suffix = uuid.uuid4().hex[:8]
    stream, subject = f"TEST_SUM_PUBLISHER_{suffix}", f"test.sum.service.{suffix}.changed"
    resource_id, message_id = _uuid(), _uuid()
    payload = {**ENVELOPE_FIELDS, "messageId": message_id, "resourceId": resource_id}
    client = await connect(
        MessagingSettings(url=url, user=user, password=SecretStr(password)),
        name="sum-service-publisher-test",
    )
    jetstream = stream_of(client)
    add_stream: Any = cast(Any, jetstream).add_stream
    await add_stream(name=stream, subjects=[subject])
    await _insert_outbox(subject, resource_id, message_id, payload)
    connection = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_URL"], autocommit=True
    )
    try:
        first = await publish_pending(connection, StreamPublisher(jetstream))
        assert first.published >= 1 and not first.failed
        assert await _published_at(resource_id) is not None
        info = await jetstream.stream_info(stream)
        assert info.state.messages == 1
        subscription = await jetstream.pull_subscribe(subject, durable=None)
        (received,) = await subscription.fetch(1, timeout=5)
        envelope: dict[str, Any] = json.loads(received.data)
        assert (
            envelope["messageId"] == message_id
            and envelope["publishedBy"] == "sum-service-publisher"
        )
        again = await publish_pending(connection, StreamPublisher(jetstream))
        assert again.published == 0  # já marcada
    finally:
        await connection.close()
        await jetstream.delete_stream(stream)
        await client.close()
        await _cleanup(resource_id)


class TransientlyFailingPublisher:
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        raise PublishError("TimeoutError", permanent=False)


async def test_a_transient_failure_keeps_the_message_pending_without_blocking_the_publisher() -> (
    None
):
    resource_id = _uuid()
    payload = {**ENVELOPE_FIELDS, "messageId": _uuid(), "resourceId": resource_id}
    await _insert_outbox(
        f"test.sum.service.{resource_id}.changed", resource_id, payload["messageId"], payload
    )
    connection = await psycopg.AsyncConnection.connect(
        os.environ["SUM_SERVICE_PUBLISHER_TEST_URL"], autocommit=True
    )
    try:
        result = await publish_pending(connection, TransientlyFailingPublisher())
        assert (result.failed, result.permanent_failure) == (True, False)
        assert await _published_at(resource_id) is None
    finally:
        await connection.close()
        await _cleanup(resource_id)
