"""Relay do outbox contra o SSOT real, com publicador simulado (docs/POSTGRESQL.md §11)."""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from support import Cleanup, connect, fetch_all, unique_suffix

from ipm_organization_relay.nats import PublishError
from ipm_organization_relay.relay import holds_lock, publish_pending, try_acquire_lock

Connection = psycopg.AsyncConnection[Any]


@dataclass
class RecordingPublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail_on: int | None = None

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail_on is not None and len(self.published) + 1 == self.fail_on:
            raise PublishError("indisponível")
        self.published.append((subject, json.loads(payload), message_id))


async def seed(cleanup: Cleanup, manager: Connection, count: int) -> list[str]:
    """Registra `count` mensagens no outbox, como o Manager faria (só `INSERT` é permitido)."""
    resource_ids: list[str] = []
    for _ in range(count):
        resource_id = cleanup.track(str(uuid.uuid7()))
        resource_ids.append(resource_id)
        message_id = str(uuid.uuid7())
        payload = {
            "messageId": message_id,
            "messageType": "desired",
            "resourceId": resource_id,
            "occurredAt": "2026-10-10T12:00:00+00:00",
            "publishedAt": "2026-10-10T12:00:00+00:00",
            "data": {"name": "relay-" + unique_suffix()},
        }
        await manager.execute(
            "INSERT INTO ipm.organization_outbox (message_id, resource_id, subject, payload)"
            " VALUES (%s, %s, %s, %s)",
            (
                message_id,
                resource_id,
                f"manager.desired.ipm.organization.{resource_id}.changed",
                Jsonb(payload),
            ),
        )
    return resource_ids


async def pending_for(relay: Connection, resource_ids: list[str]) -> list[str]:
    rows = await fetch_all(
        relay,
        "SELECT resource_id FROM ipm.organization_outbox"
        " WHERE published_at IS NULL AND resource_id = ANY(%s) ORDER BY sequence",
        resource_ids,
    )
    return [row["resource_id"] for row in rows]


async def test_publishes_in_order_marks_published_and_stamps_the_publication_time(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    ids = await seed(cleanup, organization_manager, 3)
    publisher = RecordingPublisher()
    # Mensagens pendentes de outras origens também são publicadas; só as deste teste importam.
    await publish_pending(relay, publisher, batch_size=1000)

    ours = [item for item in publisher.published if item[1]["resourceId"] in ids]
    assert [item[1]["resourceId"] for item in ours] == ids
    for subject, payload, message_id in ours:
        assert subject == f"manager.desired.ipm.organization.{payload['resourceId']}.changed"
        assert message_id == payload["messageId"]
        assert payload["publishedAt"] >= payload["occurredAt"]
    assert await pending_for(relay, ids) == []

    again = RecordingPublisher()
    await publish_pending(relay, again, batch_size=1000)
    assert [item for item in again.published if item[1]["resourceId"] in ids] == []


async def test_a_failure_interrupts_the_batch_and_only_confirmed_messages_are_marked(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    # Esvazia o que já estava pendente, para o índice da falha ser previsível.
    await publish_pending(relay, RecordingPublisher(), batch_size=1000)
    fresh = await seed(cleanup, organization_manager, 3)

    publisher = RecordingPublisher(fail_on=2)
    result = await publish_pending(relay, publisher, batch_size=1000)

    assert result.failed
    assert result.published == 1
    assert [item[1]["resourceId"] for item in publisher.published] == fresh[:1]
    assert await pending_for(relay, fresh) == fresh[1:]

    recovered = RecordingPublisher()
    await publish_pending(relay, recovered, batch_size=1000)
    assert [item[1]["resourceId"] for item in recovered.published] == fresh[1:]


async def test_only_one_instance_holds_the_session_lock(database_available: None) -> None:
    # Chave própria do teste: o relay em execução já detém a trava do outbox real.
    lock_key = "ipm.locktest_" + unique_suffix()
    first = await connect("ipm_organization_relay_login")
    second = await connect("ipm_organization_relay_login")
    try:
        assert await try_acquire_lock(first, lock_key)
        assert await holds_lock(first, lock_key)
        assert not await try_acquire_lock(second, lock_key)
        assert not await holds_lock(second, lock_key)
        await first.close()  # failover: a trava some com a sessão
        assert await try_acquire_lock(second, lock_key)
    finally:
        await second.close()
        if not first.closed:
            await first.close()
