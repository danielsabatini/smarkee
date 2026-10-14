"""Motor do Reconciler: estado reconstruído pela mensageria e publicação das `action`."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core_user_reconciler.contracts import generated
from core_user_reconciler.engine.reconciler import PublishError, Reconciler
from core_user_reconciler.settings import LoopSettings

START = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
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
class Clock:
    now: datetime = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def envelope(message_type: str, emitter: str, **fields: Any) -> bytes:
    base: dict[str, Any] = {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": emitter,
        "module": "core",
        "resourceType": "user",
        "resourceId": RESOURCE,
        "operation": "changed",
        "correlationId": "corr-1",
        "occurredAt": START.isoformat(),
        "publishedAt": START.isoformat(),
        "data": {},
    }
    base.update(fields)
    return json.dumps(base).encode()


def desired(
    *, generation: int = 1, lifecycle: str = "present", reconciliation: str = "active"
) -> bytes:
    return envelope(
        "desired",
        "manager",
        desiredGeneration=generation,
        requestedBy="anonymous",
        data={
            "lifecycle": lifecycle,
            "reconciliation": reconciliation,
            "platformAccess": "granted",
            "platformRoles": ["organization.get", "user.get"],
        },
    )


def observed(
    presence: str,
    *,
    at: datetime,
    message_id: str | None = None,
    causation: str | None = None,
    data: dict[str, Any] | None = None,
) -> bytes:
    return envelope(
        "observed",
        "observer",
        presence=presence,
        observedAt=at.isoformat(),
        data=data or {},
        **({"messageId": message_id} if message_id else {}),
        **({"causationId": causation} if causation else {}),
    )


def result(kind: str, action_id: str, *, generation: int = 1, message_id: str = "res-1") -> bytes:
    return envelope(
        kind,
        "executor",
        operation="create",
        actionId=action_id,
        desiredGeneration=generation,
        causationId="act-1",
        messageId=message_id,
        data={} if kind == "completed" else {"reason": "ProviderUnavailable", "retryable": True},
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def reconciler(publisher: FakePublisher, clock: Clock) -> Reconciler:
    return Reconciler(publisher, LoopSettings(), clock=clock, identifiers=lambda: "msg-fixed")


async def test_desired_and_absent_observation_publish_a_create_action(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired())
    assert publisher.published == []  # só o desired: ainda não decide
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-1"))

    ((subject, payload, message_id),) = publisher.published
    assert subject == f"reconciler.action.core.user.{RESOURCE}.create"
    action = generated.MessageEnvelope.model_validate(payload)
    assert (action.emitter.value, action.message_type.value, action.operation.value) == (
        "reconciler",
        "action",
        "create",
    )
    assert action.action_id == f"{RESOURCE}.1.create.obs-1" == message_id
    assert (action.desired_generation, action.causation_id) == (1, "obs-1")
    assert action.requested_by == "anonymous"
    assert action.data == {
        "reason": "Missing",
        "message": "The user does not exist in the identity provider.",
    }


async def test_observation_first_then_desired_decides_too(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-1"))
    await reconciler.on_message(desired())
    assert len(publisher.published) == 1


async def test_a_pending_action_is_not_reissued_by_repeated_evaluation(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired())
    await reconciler.on_message(observed("absent", at=clock.now))
    await reconciler.evaluate_all()
    await reconciler.evaluate_all()
    assert len(publisher.published) == 1


async def test_after_the_deadline_the_same_action_is_reissued_with_the_same_id(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired())
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-1"))
    clock.advance(121)
    # a observação precisa continuar válida (validade de 10 min)
    await reconciler.evaluate_all()
    assert [item[2] for item in publisher.published] == [f"{RESOURCE}.1.create.obs-1"] * 2


async def test_a_completed_result_waits_for_the_observation_it_caused(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired())
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-1"))
    clock.advance(1)
    await reconciler.on_message(
        result("completed", f"{RESOURCE}.1.create.obs-1", message_id="res-1")
    )
    await reconciler.evaluate_all()
    assert len(publisher.published) == 1  # a observação antiga não decide de novo

    clock.advance(1)
    await reconciler.on_message(
        observed(
            "present",
            at=clock.now,
            causation="res-1",
            data={
                "platformAccess": "granted",
                "platformRoles": ["organization.get", "user.get"],
            },
        )
    )
    assert len(publisher.published) == 1  # convergiu: nenhuma nova ação


async def test_a_failed_result_backs_off_and_then_retries_with_a_new_observation(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired())
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-1"))
    await reconciler.on_message(result("failed", f"{RESOURCE}.1.create.obs-1", message_id="res-1"))

    clock.advance(1)
    await reconciler.on_message(
        observed("absent", at=clock.now, message_id="obs-2", causation="res-1")
    )
    assert len(publisher.published) == 1  # dentro do backoff de 5 s

    clock.advance(6)
    await reconciler.evaluate_all()
    assert [item[2] for item in publisher.published][-1] == f"{RESOURCE}.1.create.obs-2"


async def test_a_new_generation_drops_the_pending_action(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired(generation=1))
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-1"))
    await reconciler.on_message(desired(generation=2))
    assert [item[1]["desiredGeneration"] for item in publisher.published] == [1, 2]


async def test_older_generation_and_older_observation_are_ignored(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired(generation=3))
    await reconciler.on_message(desired(generation=2))
    await reconciler.on_message(observed("absent", at=clock.now, message_id="obs-new"))
    await reconciler.on_message(observed("present", at=clock.now - timedelta(seconds=30)))
    state = reconciler.state_of(RESOURCE)
    assert state is not None and state.desired is not None and state.observed is not None
    assert (state.desired.generation, state.observed.presence) == (3, "absent")


async def test_suspended_desired_stops_decisions(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired(reconciliation="suspended"))
    await reconciler.on_message(observed("absent", at=clock.now))
    assert publisher.published == []


async def test_a_publish_failure_is_retried_on_the_next_evaluation(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    publisher.fail = True
    await reconciler.on_message(desired())
    await reconciler.on_message(observed("absent", at=clock.now))
    assert publisher.published == []
    publisher.fail = False
    await reconciler.evaluate_all()
    assert len(publisher.published) == 1


async def test_a_removed_tombstone_with_absent_observation_does_nothing(
    reconciler: Reconciler, publisher: FakePublisher, clock: Clock
) -> None:
    await reconciler.on_message(desired(generation=2, lifecycle="absent"))
    await reconciler.on_message(observed("absent", at=clock.now))
    assert publisher.published == []


@pytest.mark.parametrize("payload", [b"nao e json", b'{"messageId": "x"}'])
async def test_invalid_messages_are_ignored(reconciler: Reconciler, payload: bytes) -> None:
    assert await reconciler.on_message(payload) is None
    assert reconciler.resource_ids == []


async def test_messages_of_another_type_are_ignored(reconciler: Reconciler) -> None:
    other = json.loads(desired())
    other["resourceType"] = "organization"
    assert await reconciler.on_message(json.dumps(other).encode()) is None
