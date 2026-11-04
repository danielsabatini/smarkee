"""Publisher do outbox de `bsm.payment` contra o SSOT real (docs/data/POSTGRESQL.md §11)."""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from support_publisher import Cleanup, connect, fetch_all, unique_suffix

from bsm_payment.common.ports import PublishError
from bsm_payment.publisher.outbox.publication import (
    holds_lock,
    publish_pending,
    try_acquire_lock,
)

Connection = psycopg.AsyncConnection[Any]


@dataclass
class RecordingPublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail_on: int | None = None
    permanent: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail_on is not None and len(self.published) + 1 == self.fail_on:
            raise PublishError("indisponível", permanent=self.permanent)
        self.published.append((subject, json.loads(payload), message_id))


async def enqueue(
    api: Connection,
    *,
    resource_id: str,
    generation: int = 1,
    display_name: str = "Visa",
) -> str:
    message_id = str(uuid.uuid7())
    correlation_id = str(uuid.uuid7())
    payload = {
        "messageId": message_id,
        "schemaVersion": "1.0",
        "messageType": "desired",
        "emitter": "api",
        "module": "bsm",
        "resourceType": "payment",
        "resourceId": resource_id,
        "operation": "changed",
        "desiredGeneration": generation,
        "requestedBy": "user-1",
        "correlationId": correlation_id,
        "causationId": correlation_id,
        "occurredAt": "2026-10-16T10:00:00Z",
        "data": {
            "lifecycle": "present",
            "reconciliation": "active",
            "ownerAccountId": "user-1",
            "customerAccountId": "user-1",
            "displayName": display_name,
            "provider": "mercadopago",
            "methodType": "credit_card",
            "providerToken": "sim_visa_4242",
        },
    }
    await api.execute(
        "INSERT INTO bsm.payment_outbox (message_id, resource_id, subject, payload)"
        " VALUES (%s, %s, %s, %s)",
        (message_id, resource_id, f"desired.bsm.payment.{resource_id}", Jsonb(payload)),
    )
    return message_id


async def test_publishes_in_sequence_order_and_marks_published_at(
    cleanup: Cleanup, api: Connection, publisher_conn: Connection
) -> None:
    resource_id = cleanup.track(f"pub-{unique_suffix()}")
    first = await enqueue(api, resource_id=resource_id, generation=1, display_name="Um")
    second = await enqueue(api, resource_id=resource_id, generation=2, display_name="Dois")
    recorder = RecordingPublisher()

    result = await publish_pending(publisher_conn, recorder, batch_size=50)

    ours = [item for item in recorder.published if item[2] in {first, second}]
    assert result.published >= 2
    assert result.failed is False
    assert [item[2] for item in ours] == [first, second]
    assert all("publishedAt" in item[1] for item in ours)

    rows = await fetch_all(
        publisher_conn,
        "SELECT message_id, published_at FROM bsm.payment_outbox"
        " WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )
    assert [row["message_id"] for row in rows] == [first, second]
    assert all(row["published_at"] is not None for row in rows)


async def test_stops_at_first_failure_to_preserve_order(
    cleanup: Cleanup, api: Connection, publisher_conn: Connection
) -> None:
    resource_id = cleanup.track(f"pub-{unique_suffix()}")
    await publish_pending(publisher_conn, RecordingPublisher(), batch_size=500)

    first = await enqueue(api, resource_id=resource_id, generation=1, display_name="Um")
    second = await enqueue(api, resource_id=resource_id, generation=2, display_name="Dois")
    recorder = RecordingPublisher(fail_on=1)

    result = await publish_pending(publisher_conn, recorder, batch_size=50)
    assert result.published == 0
    assert result.failed is True
    assert result.permanent_failure is False

    rows = await fetch_all(
        publisher_conn,
        "SELECT message_id, published_at FROM bsm.payment_outbox"
        " WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )
    by_id = {row["message_id"]: row for row in rows}
    assert by_id[first]["published_at"] is None
    assert by_id[second]["published_at"] is None


async def test_advisory_lock_allows_only_one_leader(publisher_conn: Connection) -> None:
    second = await connect("bsm_payment_publisher_login")
    try:
        assert await try_acquire_lock(publisher_conn) is True
        assert await holds_lock(publisher_conn) is True
        assert await try_acquire_lock(second) is False
        assert await holds_lock(second) is False
    finally:
        await second.close()
        await publisher_conn.execute("SELECT pg_advisory_unlock_all()")
