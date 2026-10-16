import json
from dataclasses import dataclass, field
from typing import Any

from sum_service_observer.domain.authorization import Authorization, ProviderError
from sum_service_observer.engine.observer import Observer, owns

OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
RID = "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b"
CATALOG = {"ipm": ("ipm.organization.get", "ipm.organization.list")}


@dataclass
class FakeReader:
    exists: bool = True
    roles: frozenset[str] = frozenset()
    fail: bool = False

    async def user_exists(self, user_id: str) -> bool:
        if self.fail:
            raise ProviderError("HTTP 503")
        return self.exists

    async def authorizations(self, user_id: str) -> list[Authorization]:
        return [Authorization("proj-ipm", self.roles)] if self.roles else []


@dataclass
class Recorder:
    sent: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        self.sent.append((subject, json.loads(payload), message_id))


def envelope(message_type: str, message_id: str, **fields: Any) -> bytes:
    base: dict[str, Any] = {
        "messageId": message_id,
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": "manager",
        "module": "sum",
        "resourceType": "service",
        "resourceId": RID,
        "operation": "changed",
        "occurredAt": "2026-10-15T14:00:00Z",
        "publishedAt": "2026-10-15T14:00:00Z",
        "publishedBy": "sum-service-publisher",
        "correlationId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1c",
        "data": {},
    }
    base.update(fields)
    return json.dumps(base).encode()


def desired(generation: int, lifecycle: str = "present", message_id: str = "m-desired") -> bytes:
    return envelope(
        "desired",
        message_id,
        desiredGeneration=generation,
        data={
            "lifecycle": lifecycle,
            "ownerAccountId": OWNER,
            "service": "ipm",
            "serviceRoles": [],
        },
    )


def result(message_type: str, message_id: str) -> bytes:
    return envelope(message_type, message_id, emitter="executor", desiredGeneration=1)


def observer(reader: FakeReader, recorder: Recorder) -> Observer:
    ids = iter(f"id-{n}" for n in range(1, 1000))
    return Observer(reader, recorder, CATALOG, identifiers=lambda: next(ids))


async def test_a_new_desired_generation_is_observed_once_with_the_roles_of_the_service() -> None:
    recorder = Recorder()
    watcher = observer(
        FakeReader(roles=frozenset({"ipm.organization.get", "ipm.outro.x"})), recorder
    )
    await watcher.on_message(desired(1))
    assert len(recorder.sent) == 1
    subject, body, message_id = recorder.sent[0]
    assert subject == f"observer.observed.sum.service.{RID}.changed"
    assert body["presence"] == "present" and body["data"] == {
        "serviceRoles": ["ipm.organization.get"]
    }
    assert message_id == body["messageId"]
    assert body["causationId"] == "m-desired"  # observação causada pelo desired


async def test_the_same_generation_again_observes_nothing_new() -> None:
    recorder = Recorder()
    watcher = observer(FakeReader(), recorder)
    await watcher.on_message(desired(1))
    await watcher.on_message(desired(1, message_id="m-desired-again"))
    assert len(recorder.sent) == 1


async def test_a_result_triggers_an_observation_caused_by_it() -> None:
    recorder = Recorder()
    watcher = observer(FakeReader(), recorder)
    await watcher.on_message(desired(1))
    await watcher.on_message(result("completed", "m-result"))
    assert recorder.sent[-1][1]["causationId"] == "m-result"


async def test_a_read_failure_is_published_as_unknown_never_as_absent() -> None:
    recorder = Recorder()
    watcher = observer(FakeReader(fail=True), recorder)
    await watcher.on_message(desired(1))
    assert recorder.sent[0][1]["presence"] == "unknown"


async def test_a_result_without_a_known_desired_is_ignored() -> None:
    recorder = Recorder()
    await observer(FakeReader(), recorder).on_message(result("completed", "m-result"))
    assert recorder.sent == []


async def test_a_converged_removal_stops_the_periodic_observation() -> None:
    recorder = Recorder()
    watcher = observer(FakeReader(roles=frozenset()), recorder)
    await watcher.on_message(desired(1))
    await watcher.on_message(desired(2, lifecycle="absent", message_id="m-desired-2"))
    recorder.sent.clear()
    await watcher.observe_all()
    assert recorder.sent == []


async def test_the_periodic_observation_refreshes_the_active_links() -> None:
    recorder = Recorder()
    watcher = observer(FakeReader(), recorder)
    await watcher.on_message(desired(1))
    recorder.sent.clear()
    await watcher.observe_all()
    assert len(recorder.sent) == 1


async def test_an_absent_user_is_published_as_absent() -> None:
    recorder = Recorder()
    await observer(FakeReader(exists=False), recorder).on_message(desired(1))
    assert recorder.sent[0][1]["presence"] == "absent"


# ---------------------------------------------------------------------- partição e entrada inválida


def partitioned(reader: FakeReader, recorder: Recorder, index: int, count: int) -> Observer:
    return Observer(
        reader,
        recorder,
        CATALOG,
        partition_index=index,
        partition_count=count,
        identifiers=lambda: "id-1",
    )


def test_owns_is_deterministic_and_each_resource_has_exactly_one_owner() -> None:
    count = 3
    owners = [index for index in range(count) if owns(RID, index, count)]
    assert len(owners) == 1
    assert owns(RID, owners[0], count) is True  # repetir dá o mesmo resultado


async def test_an_instance_ignores_a_resource_of_another_partition() -> None:
    mine = next(index for index in range(2) if owns(RID, index, 2))
    other = 1 - mine
    recorder = Recorder()
    await partitioned(FakeReader(), recorder, other, 2).on_message(desired(1))
    assert recorder.sent == []
    await partitioned(FakeReader(), recorder, mine, 2).on_message(desired(1))
    assert len(recorder.sent) == 1


async def test_the_periodic_round_skips_resources_of_another_partition() -> None:
    mine = next(index for index in range(2) if owns(RID, index, 2))
    recorder = Recorder()
    watcher = partitioned(FakeReader(), recorder, mine, 2)
    await watcher.on_message(desired(1))
    recorder.sent.clear()
    watcher._partition = (1 - mine, 2)  # pyright: ignore[reportPrivateUsage]
    await watcher.observe_all()
    assert recorder.sent == []


async def test_a_desired_without_a_valid_lifecycle_is_not_observed() -> None:
    recorder = Recorder()
    watcher = observer(FakeReader(), recorder)
    for lifecycle in (None, "", "unknown"):
        data: dict[str, Any] = {"ownerAccountId": OWNER, "service": "ipm", "serviceRoles": []}
        if lifecycle is not None:
            data["lifecycle"] = lifecycle
        await watcher.on_message(envelope("desired", "m", desiredGeneration=1, data=data))
    assert recorder.sent == []
    assert watcher.watch_of(RID) is None
