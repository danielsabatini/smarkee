"""Motor do Observer: gatilhos de observação, partição e publicação de `observed`."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from core_user_observer.contracts import generated
from core_user_observer.domain.observation import Observation
from core_user_observer.engine.observer import Observer, PublishError, owns
from core_user_observer.settings import PartitionSettings, UserObserverSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
RESOURCE = "user-1"


@dataclass
class FakePublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError
        self.published.append((subject, json.loads(payload), message_id))


@dataclass
class FakeObservation:
    results: list[Observation] = field(default_factory=lambda: [Observation("absent", {})])
    reads: list[str] = field(default_factory=lambda: [])

    async def __call__(self, reader: object, user_id: str) -> Observation:
        self.reads.append(user_id)
        return self.results[min(len(self.reads), len(self.results)) - 1]


def envelope(message_type: str, emitter: str, resource_id: str = RESOURCE, **fields: Any) -> bytes:
    base: dict[str, Any] = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": emitter,
        "module": "core",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": "changed",
        "correlationId": "corr-1",
        "occurredAt": NOW.isoformat(),
        "publishedAt": NOW.isoformat(),
        "data": {},
    }
    base.update(fields)
    return json.dumps(base).encode()


def desired(
    resource_id: str = RESOURCE,
    *,
    generation: int = 1,
    lifecycle: str = "present",
    message_id: str | None = None,
) -> bytes:
    return envelope(
        "desired",
        "manager",
        resource_id,
        desiredGeneration=generation,
        data={"lifecycle": lifecycle, "reconciliation": "active", "platformAccess": "granted"},
        **({"messageId": message_id} if message_id else {}),
    )


def result(kind: str = "completed", *, message_id: str = "res-1") -> bytes:
    return envelope(
        kind,
        "executor",
        operation="create",
        actionId="a-1",
        desiredGeneration=1,
        causationId="act-1",
        messageId=message_id,
    )


def build(
    observation: FakeObservation,
    publisher: FakePublisher,
    *,
    partition: PartitionSettings | None = None,
) -> Observer:
    settings = UserObserverSettings(partition=partition or PartitionSettings())
    return Observer(
        object(),  # type: ignore[arg-type]
        publisher,
        settings,
        clock=lambda: NOW,
        identifiers=lambda: "msg-fixed",
        observe_resource=observation,
    )


async def test_a_new_desired_triggers_an_observation_caused_by_it() -> None:
    publisher, observation = FakePublisher(), FakeObservation()
    observer = build(observation, publisher)

    await observer.on_message(desired(message_id="des-1"))

    ((subject, payload, message_id),) = publisher.published
    assert subject == f"observer.observed.core.user.{RESOURCE}.changed"
    envelope_ = generated.MessageEnvelope.model_validate(payload)
    assert (envelope_.emitter.value, envelope_.message_type.value) == ("observer", "observed")
    assert (envelope_.presence.value if envelope_.presence else None) == "absent"
    assert envelope_.causation_id == "des-1" and envelope_.observed_at == NOW
    assert envelope_.correlation_id == "corr-1" and message_id == envelope_.message_id


async def test_the_same_generation_does_not_trigger_again_but_a_new_one_does() -> None:
    publisher, observation = FakePublisher(), FakeObservation()
    observer = build(observation, publisher)
    await observer.on_message(desired(generation=1))
    await observer.on_message(desired(generation=1))  # reentrega ou mudança só de reconciliation
    assert len(publisher.published) == 1
    await observer.on_message(desired(generation=2))
    assert len(publisher.published) == 2
    await observer.on_message(desired(generation=1))  # geração mais antiga
    assert len(publisher.published) == 2


async def test_a_result_triggers_an_observation_caused_by_the_result() -> None:
    publisher, observation = FakePublisher(), FakeObservation([Observation("present", {})])
    observer = build(observation, publisher)
    await observer.on_message(desired())
    await observer.on_message(result("completed", message_id="res-9"))
    assert publisher.published[-1][1]["causationId"] == "res-9"
    await observer.on_message(result("failed", message_id="res-10"))
    assert publisher.published[-1][1]["causationId"] == "res-10"


async def test_unknown_is_published_as_unknown() -> None:
    publisher = FakePublisher()
    observer = build(FakeObservation([Observation("unknown", {})]), publisher)
    await observer.on_message(desired())
    assert publisher.published[0][1]["presence"] == "unknown"


async def test_it_only_observes_its_partition() -> None:
    ids = [f"user-{index}" for index in range(40)]
    mine = [i for i in ids if owns(i, 0, 2)]
    others = [i for i in ids if not owns(i, 0, 2)]
    assert mine and others and len(mine) + len(others) == 40
    publisher, observation = FakePublisher(), FakeObservation()
    observer = build(observation, publisher, partition=PartitionSettings(index=0, count=2))
    for resource_id in ids:
        await observer.on_message(desired(resource_id))
    assert sorted(observation.reads) == sorted(mine)
    assert all(owns(i, 0, 2) is True for i in observation.reads)
    # Cada recurso pertence a exatamente uma instância.
    assert all(owns(i, 0, 2) != owns(i, 1, 2) for i in ids)


async def test_periodic_observation_covers_owned_resources_until_the_removal_converges() -> None:
    publisher = FakePublisher()
    observation = FakeObservation([Observation("present", {})])
    observer = build(observation, publisher)
    await observer.on_message(desired("a"))
    await observer.on_message(desired("b"))
    observation.reads.clear()
    await observer.observe_all()
    assert sorted(observation.reads) == ["a", "b"]

    await observer.on_message(desired("a", generation=2, lifecycle="absent"))
    observation.results = [Observation("absent", {})]
    observation.reads.clear()
    await observer.observe_all()
    watch = observer.watch_of("a")
    assert watch is not None and watch.tombstone
    observation.reads.clear()
    await observer.observe_all()
    assert "a" not in observation.reads  # tombstone: não observa mais


async def test_a_publish_failure_does_not_stop_the_observer() -> None:
    publisher = FakePublisher(fail=True)
    observer = build(FakeObservation(), publisher)
    await observer.on_message(desired())
    assert publisher.published == []
    publisher.fail = False
    await observer.observe_all()
    assert len(publisher.published) == 1


@pytest.mark.parametrize("payload", [b"nao e json", b'{"messageId": "x"}'])
async def test_invalid_messages_are_ignored(payload: bytes) -> None:
    publisher = FakePublisher()
    await build(FakeObservation(), publisher).on_message(payload)
    assert publisher.published == []


async def test_messages_of_another_type_are_ignored() -> None:
    publisher = FakePublisher()
    other = json.loads(desired())
    other["resourceType"] = "organization"
    await build(FakeObservation(), publisher).on_message(json.dumps(other).encode())
    assert publisher.published == []
