"""Relay do outbox contra o SSOT real, com publicador simulado (docs/POSTGRESQL.md §11)."""

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from support import Cleanup, connect, fetch_all, requested_message, unique_suffix

from core.manager.kinds import ORGANIZATION
from core.manager.requested import RequestedHandler
from core.messaging.publisher import PublishError
from core.relay import holds_lock, publish_pending, try_acquire_lock

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
    handler = RequestedHandler()
    resource_ids: list[str] = []
    for _ in range(count):
        resource_id = cleanup.track(str(uuid.uuid7()))
        resource_ids.append(resource_id)
        await handler.handle(
            manager,
            ORGANIZATION,
            requested_message(
                resource_type="organization",
                resource_id=resource_id,
                operation="create",
                requested_by="relay-" + unique_suffix(),
                data={
                    "operationId": str(uuid.uuid7()),
                    "requestDigest": "0" * 64,
                    "specification": {
                        "name": "relay-" + unique_suffix(),
                        "platformAccess": "granted",
                    },
                },
            ),
        )
    return resource_ids


async def pending_for(relay: Connection, resource_ids: list[str]) -> list[str]:
    rows = await fetch_all(
        relay,
        "SELECT resource_id FROM core.organization_outbox"
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
    await publish_pending(relay, ORGANIZATION, publisher, batch_size=1000)

    ours = [item for item in publisher.published if item[1]["resourceId"] in ids]
    assert [item[1]["resourceId"] for item in ours] == ids
    for subject, payload, message_id in ours:
        assert subject == f"manager.desired.core.organization.{payload['resourceId']}.changed"
        assert message_id == payload["messageId"]
        assert payload["publishedAt"] >= payload["occurredAt"]
    assert await pending_for(relay, ids) == []

    again = RecordingPublisher()
    await publish_pending(relay, ORGANIZATION, again, batch_size=1000)
    assert [item for item in again.published if item[1]["resourceId"] in ids] == []


async def test_a_failure_interrupts_the_batch_and_only_confirmed_messages_are_marked(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    # Esvazia o que já estava pendente, para o índice da falha ser previsível.
    await publish_pending(relay, ORGANIZATION, RecordingPublisher(), batch_size=1000)
    fresh = await seed(cleanup, organization_manager, 3)

    publisher = RecordingPublisher(fail_on=2)
    result = await publish_pending(relay, ORGANIZATION, publisher, batch_size=1000)

    assert result.failed
    assert result.published == 1
    assert [item[1]["resourceId"] for item in publisher.published] == fresh[:1]
    assert await pending_for(relay, fresh) == fresh[1:]

    recovered = RecordingPublisher()
    await publish_pending(relay, ORGANIZATION, recovered, batch_size=1000)
    assert [item[1]["resourceId"] for item in recovered.published] == fresh[1:]


async def test_only_one_instance_holds_the_session_lock(database_available: None) -> None:
    # Chave própria do teste: o relay do serviço em execução já detém a trava do outbox real.
    kind = dataclasses.replace(ORGANIZATION, resource_type="locktest" + unique_suffix())
    first = await connect("core_relay_login")
    second = await connect("core_relay_login")
    try:
        assert await try_acquire_lock(first, kind)
        assert await holds_lock(first, kind)
        assert not await try_acquire_lock(second, kind)
        assert not await holds_lock(second, kind)
        await first.close()  # failover: a trava some com a sessão
        assert await try_acquire_lock(second, kind)
    finally:
        await second.close()
        if not first.closed:
            await first.close()
