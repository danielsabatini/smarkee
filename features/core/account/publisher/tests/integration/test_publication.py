"""Publisher do outbox contra o SSOT real, com publicador simulado (docs/POSTGRESQL.md §11)."""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from support import Cleanup, connect, fetch_all, unique_suffix

from core_account_publisher.domain.publication import PublishError
from core_account_publisher.outbox.publication import holds_lock, publish_pending, try_acquire_lock

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
            "INSERT INTO core.account_outbox (message_id, resource_id, subject, payload)"
            " VALUES (%s, %s, %s, %s)",
            (
                message_id,
                resource_id,
                f"manager.desired.core.account.{resource_id}.changed",
                Jsonb(payload),
            ),
        )
    return resource_ids


async def pending_for(outbox_reader: Connection, resource_ids: list[str]) -> list[str]:
    rows = await fetch_all(
        outbox_reader,
        "SELECT resource_id FROM core.account_outbox"
        " WHERE published_at IS NULL AND resource_id = ANY(%s) ORDER BY sequence",
        resource_ids,
    )
    return [row["resource_id"] for row in rows]


async def test_publishes_in_order_marks_published_and_stamps_the_publication_time(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    ids = await seed(cleanup, account_manager, 3)
    publisher = RecordingPublisher()
    # Mensagens pendentes de outras origens também são publicadas; só as deste teste importam.
    await publish_pending(outbox_reader, publisher, batch_size=1000)

    ours = [item for item in publisher.published if item[1]["resourceId"] in ids]
    assert [item[1]["resourceId"] for item in ours] == ids
    for subject, payload, message_id in ours:
        assert subject == f"manager.desired.core.account.{payload['resourceId']}.changed"
        assert message_id == payload["messageId"]
        assert payload["publishedAt"] >= payload["occurredAt"]
    assert await pending_for(outbox_reader, ids) == []

    again = RecordingPublisher()
    await publish_pending(outbox_reader, again, batch_size=1000)
    assert [item for item in again.published if item[1]["resourceId"] in ids] == []


async def test_a_failure_interrupts_the_batch_and_only_confirmed_messages_are_marked(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    # Esvazia o que já estava pendente, para o índice da falha ser previsível.
    await publish_pending(outbox_reader, RecordingPublisher(), batch_size=1000)
    fresh = await seed(cleanup, account_manager, 3)

    publisher = RecordingPublisher(fail_on=2)
    result = await publish_pending(outbox_reader, publisher, batch_size=1000)

    assert result.failed
    assert result.published == 1
    assert [item[1]["resourceId"] for item in publisher.published] == fresh[:1]
    assert await pending_for(outbox_reader, fresh) == fresh[1:]

    recovered = RecordingPublisher()
    await publish_pending(outbox_reader, recovered, batch_size=1000)
    assert [item[1]["resourceId"] for item in recovered.published] == fresh[1:]


async def test_a_permanent_refusal_blocks_the_queue_and_is_reported(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    await publish_pending(outbox_reader, RecordingPublisher(), batch_size=1000)
    fresh = await seed(cleanup, account_manager, 2)

    result = await publish_pending(
        outbox_reader, RecordingPublisher(fail_on=1, permanent=True), batch_size=1000
    )

    assert result.failed and result.permanent_failure
    assert result.published == 0
    # A ordem é preservada: nada depois da mensagem recusada é publicado.
    assert await pending_for(outbox_reader, fresh) == fresh


async def test_only_one_instance_holds_the_session_lock(database_available: None) -> None:
    # Chave própria do teste: o Publisher em execução já detém a trava do outbox real.
    lock_key = "core.locktest_" + unique_suffix()
    first = await connect("core_account_publisher_login")
    second = await connect("core_account_publisher_login")
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


async def test_the_publisher_identifies_itself_without_changing_the_emitter(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    ids = await seed(cleanup, account_manager, 1)
    publisher = RecordingPublisher()
    await publish_pending(outbox_reader, publisher, batch_size=1000)

    ours = [item[1] for item in publisher.published if item[1]["resourceId"] in ids]
    assert [payload["publishedBy"] for payload in ours] == ["core-account-publisher"]
    assert all("emitter" not in payload or payload["emitter"] == "manager" for payload in ours)
