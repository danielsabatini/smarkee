"""Motor do Observer: gatilhos de observação, partição e publicação de `observed`."""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from ipm_organization.common.contracts import generated
from ipm_organization.common.logging_config import JsonFormatter, build_resource
from ipm_organization.common.ports import PublishError
from ipm_organization.observer.domain.observation import Observation
from ipm_organization.observer.engine.observer import Observer, owns
from ipm_organization.observer.settings import OrganizationObserverSettings, PartitionSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
RESOURCE = "organization-1"


@dataclass
class FakePublisher:
    published: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError("unavailable")
        self.published.append((subject, json.loads(payload), message_id))


@dataclass
class FakeObservation:
    results: list[Observation] = field(default_factory=lambda: [Observation("absent", {})])
    reads: list[str] = field(default_factory=lambda: [])

    async def __call__(self, reader: object, organization_id: str) -> Observation:
        self.reads.append(organization_id)
        return self.results[min(len(self.reads), len(self.results)) - 1]


def envelope(message_type: str, emitter: str, resource_id: str = RESOURCE, **fields: Any) -> bytes:
    base: dict[str, Any] = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": emitter,
        "module": "ipm",
        "resourceType": "organization",
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
    settings = OrganizationObserverSettings(partition=partition or PartitionSettings())
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
    assert subject == f"observer.observed.ipm.organization.{RESOURCE}.changed"
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
    ids = [f"organization-{index}" for index in range(40)]
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
    other["resourceType"] = "service"
    await build(FakeObservation(), publisher).on_message(json.dumps(other).encode())
    assert publisher.published == []


async def test_the_log_of_a_periodic_read_carries_the_observed_resource() -> None:
    """A rodada periódica não nasce de uma mensagem: o recurso vem do próprio Observer."""
    seen: list[dict[str, Any]] = []

    class Capturing(FakeObservation):
        async def __call__(self, reader: object, resource_id: str) -> Observation:
            line = JsonFormatter(build_resource("observer")).format(
                logging.LogRecord("httpx", logging.INFO, "", 0, "HTTP Request", None, None)
            )
            seen.append(json.loads(line)["attributes"])
            return await super().__call__(reader, resource_id)

    observer = build(Capturing([Observation("present", {})]), FakePublisher())
    await observer.on_message(desired("org-periodic"))
    seen.clear()

    await observer.observe_all()

    assert seen[0]["smarkee.resource.id"] == "org-periodic"
    assert seen[0]["smarkee.actor.type"] == "system"
    assert (
        seen[0]["smarkee.organization.id"] == "org-periodic"
    )  # o recurso é a própria Organization


async def test_the_observation_context_does_not_leak_to_the_caller() -> None:
    from ipm_organization.common.logging_config import save_context

    before = save_context()
    observer = build(FakeObservation([Observation("present", {})]), FakePublisher())
    await observer.observe_resource("other", causation_id=None)
    assert save_context() == before


async def test_observed_carries_the_generation_known_before_the_read() -> None:
    """O Manager só confirma uma geração com uma observação posterior a ela (decisão 0072)."""
    publisher, observation = FakePublisher(), FakeObservation()
    observer = build(observation, publisher)

    await observer.on_message(desired(generation=3))

    ((_, payload, _),) = publisher.published
    assert payload["observedGeneration"] == 3


async def test_a_desired_arriving_during_the_read_is_not_attributed_to_it() -> None:
    publisher = FakePublisher()

    class GenerationChangesDuringRead:
        async def __call__(self, reader: object, resource_id: str) -> Observation:
            watch = observer.watch_of(resource_id)
            assert watch is not None
            watch.generation = 2  # um `desired` novo chegou enquanto o provedor era lido
            return Observation("absent", {})

    observer = build(GenerationChangesDuringRead(), publisher)  # type: ignore[arg-type]

    await observer.on_message(desired(generation=1))

    ((_, payload, _),) = publisher.published
    assert payload["observedGeneration"] == 1
