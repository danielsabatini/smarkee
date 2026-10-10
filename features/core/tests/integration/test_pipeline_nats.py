"""Pipeline completo no ambiente de dev: requested → Manager → outbox → relay → DESIRED.

Requer a stack de dev no ar e a senha do NATS em `CORE_TEST_NATS_PASSWORD` (a do `broker/.env`).
Exemplo, a partir de `features/core`:

    NATS_ENV=../../infrastructure/dev/broker/.env
    export CORE_TEST_NATS_PASSWORD=$(grep ^NATS_PASSWORD= $NATS_ENV | cut -d= -f2)

Sem ela, os testes são pulados.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from pydantic import SecretStr
from support import (
    DATABASE_HOST,
    DATABASE_PORT,
    DEFAULT_DIGEST,
    Cleanup,
    requested_message,
    unique_suffix,
)

from core.contracts import generated
from core.database import open_pool
from core.manager.kinds import ORGANIZATION
from core.messaging.jetstream import JetStreamPublisher, RequestedConsumer, connect, jetstream_of
from core.relay import OutboxRelay
from core.settings import DatabaseSettings, NatsSettings

NATS_PASSWORD = os.environ.get("CORE_TEST_NATS_PASSWORD")
NATS_URL = os.environ.get("CORE_TEST_NATS_URL", "nats://localhost:4222")

pytestmark = pytest.mark.skipif(
    NATS_PASSWORD is None, reason="CORE_TEST_NATS_PASSWORD não definida"
)


@dataclass
class Pipeline:
    publisher: JetStreamPublisher
    jetstream: Any


@pytest_asyncio.fixture
async def pipeline(cleanup: Cleanup) -> AsyncIterator[Pipeline]:
    assert NATS_PASSWORD is not None
    database = DatabaseSettings(
        host=DATABASE_HOST,
        port=int(DATABASE_PORT),
        organization_manager_password=SecretStr("core_organization_manager_login"),
        relay_password=SecretStr("core_relay_login"),
    )
    client = await connect(
        NatsSettings(url=NATS_URL, password=SecretStr(NATS_PASSWORD)), name="core-test"
    )
    jetstream = jetstream_of(client)
    publisher = JetStreamPublisher(jetstream)
    pool = await open_pool(database, "organization_manager")
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(
            RequestedConsumer(jetstream, pool, ORGANIZATION, fetch_timeout_seconds=0.5).run(stop)
        ),
        asyncio.create_task(OutboxRelay(database, ORGANIZATION, publisher).run(stop)),
    ]
    yield Pipeline(publisher, jetstream)
    stop.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    for resource_id in cleanup.resource_ids:
        await jetstream.purge_stream(
            "DESIRED", subject=f"manager.desired.core.organization.{resource_id}.changed"
        )
    await pool.close()
    await client.close()


def message_for(
    cleanup: Cleanup, *, operation_id: str | None = None, resource_id: str | None = None
) -> dict[str, Any]:
    return requested_message(
        resource_type="organization",
        resource_id=cleanup.track(resource_id or str(uuid.uuid7())),
        operation="create",
        requested_by="pipeline-user",
        data={
            "operationId": operation_id or str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "specification": {"name": "pipe-" + unique_suffix(), "platformAccess": "granted"},
        },
    )


async def last_desired(
    jetstream: Any, resource_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    subject = f"manager.desired.core.organization.{resource_id}.changed"
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            raw = await jetstream.get_last_msg("DESIRED", subject)
            return json.loads(raw.data)
        except Exception:  # ainda não publicado: tenta de novo até o prazo
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.2)


async def test_requested_becomes_desired_in_the_stream(
    cleanup: Cleanup, pipeline: Pipeline
) -> None:
    message = message_for(cleanup)
    subject = f"api.requested.core.organization.{message['resourceId']}.create"
    await pipeline.publisher.publish(
        subject, json.dumps(message).encode(), message_id=message["messageId"]
    )

    desired = await last_desired(pipeline.jetstream, message["resourceId"])

    envelope = generated.MessageEnvelope.model_validate(desired)
    assert envelope.message_type.value == "desired"
    assert envelope.desired_generation == 1
    assert envelope.causation_id == message["messageId"]
    assert envelope.data["name"] == message["data"]["specification"]["name"]
    assert envelope.data["ownerUserId"] == "pipeline-user"


async def test_redelivered_request_with_a_new_message_id_does_not_publish_a_second_desired(
    cleanup: Cleanup, pipeline: Pipeline
) -> None:
    first = message_for(cleanup)
    subject = f"api.requested.core.organization.{first['resourceId']}.create"
    await pipeline.publisher.publish(
        subject, json.dumps(first).encode(), message_id=first["messageId"]
    )
    original = await last_desired(pipeline.jetstream, first["resourceId"])

    repeat = {**first, "messageId": str(uuid.uuid7())}
    await pipeline.publisher.publish(
        subject, json.dumps(repeat).encode(), message_id=repeat["messageId"]
    )
    await asyncio.sleep(2.0)

    assert await last_desired(pipeline.jetstream, first["resourceId"]) == original
