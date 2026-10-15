import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from sum_service_executor.engine.executor import Executor, PublishError, TransientFailureError
from sum_service_executor.provider.zitadel import Grant, ProviderError

OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
RID = "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b"
ACTION_ID = f"{RID}.2.update.m-observed"
CATALOG = {"ipm": ("ipm.organization.get", "ipm.organization.list")}
ROLES = ("ipm.organization.get", "ipm.organization.list")


def envelope(message_type: str, message_id: str, **fields: Any) -> bytes:
    base: dict[str, Any] = {
        "messageId": message_id,
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": "reconciler" if message_type == "action" else "manager",
        "module": "sum",
        "resourceType": "service",
        "resourceId": RID,
        "operation": "update" if message_type == "action" else "changed",
        "occurredAt": "2026-10-15T14:00:00Z",
        "publishedAt": "2026-10-15T14:00:00Z",
        "publishedBy": "sum-service-publisher",
        "correlationId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1c",
        "data": {},
    }
    base.update(fields)
    return json.dumps(base).encode()


def desired(generation: int, lifecycle: str = "present") -> bytes:
    return envelope(
        "desired",
        "m-desired",
        desiredGeneration=generation,
        data={
            "lifecycle": lifecycle,
            "ownerUserId": OWNER,
            "service": "ipm",
            "serviceRoles": list(ROLES) if lifecycle == "present" else [],
        },
    )


def action(generation: int = 2) -> bytes:
    return envelope(
        "action",
        "m-action",
        actionId=ACTION_ID,
        desiredGeneration=generation,
        data={"reason": "Drift", "message": "x"},
    )


@dataclass
class FakeGranter:
    grants_by_user: dict[str, list[Grant]] = field(default_factory=lambda: {})
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail: ProviderError | None = None

    def project_of(self, role: str) -> str:
        return "proj-ipm"

    async def grants(self, user_id: str) -> list[Grant]:
        if self.fail is not None:
            raise self.fail
        return list(self.grants_by_user.get(user_id, []))

    async def create_grant(self, user_id: str, project_id: str, roles: list[str]) -> None:
        self.calls.append(("create", user_id, tuple(roles)))
        self.grants_by_user.setdefault(user_id, []).append(
            Grant("g-1", project_id, frozenset(roles))
        )

    async def update_grant(self, grant_id: str, roles: list[str]) -> None:
        self.calls.append(("update", grant_id, tuple(roles)))

    async def remove_grant(self, grant_id: str) -> None:
        self.calls.append(("remove", grant_id))


@dataclass
class FakeDesired:
    raw: bytes | None

    async def current(self, resource_id: str) -> bytes | None:
        return self.raw


@dataclass
class FakePublisher:
    sent: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError("down")
        self.sent.append((subject, json.loads(payload), message_id))


def executor(granter: FakeGranter, raw: bytes | None, publisher: FakePublisher) -> Executor:
    ids = iter(f"id-{n}" for n in range(1, 1000))
    return Executor(granter, FakeDesired(raw), publisher, CATALOG, identifiers=lambda: next(ids))


async def test_a_current_action_grants_the_roles_and_publishes_completed() -> None:
    granter, publisher = FakeGranter(), FakePublisher()
    await executor(granter, desired(2), publisher).on_action(action(2))
    assert granter.calls == [("create", OWNER, tuple(sorted(ROLES)))]
    ((subject, body, message_id),) = publisher.sent
    assert subject == f"executor.completed.sum.service.{RID}"
    assert message_id == f"{ACTION_ID}.completed"  # dedupe do resultado
    assert body["messageType"] == "completed" and body["actionId"] == ACTION_ID
    assert body["causationId"] == "m-action" and body["data"] == {}


async def test_a_stale_action_executes_nothing_and_publishes_nothing() -> None:
    granter, publisher = FakeGranter(), FakePublisher()
    await executor(granter, desired(3), publisher).on_action(action(2))
    assert granter.calls == [] and publisher.sent == []


async def test_a_missing_desired_executes_nothing() -> None:
    granter, publisher = FakeGranter(), FakePublisher()
    await executor(granter, None, publisher).on_action(action(2))
    assert granter.calls == [] and publisher.sent == []


async def test_a_disabled_link_revokes_the_roles_of_the_catalog() -> None:
    granter = FakeGranter()
    granter.grants_by_user[OWNER] = [Grant("g-9", "proj-ipm", frozenset(ROLES))]
    publisher = FakePublisher()
    await executor(granter, desired(2, lifecycle="absent"), publisher).on_action(action(2))
    assert granter.calls == [("remove", "g-9")]
    assert publisher.sent[0][1]["messageType"] == "completed"


async def test_a_permanent_refusal_publishes_failed_with_the_reason() -> None:
    granter = FakeGranter(fail=ProviderError("Rejected", retryable=False, detail="HTTP 400"))
    publisher = FakePublisher()
    await executor(granter, desired(2), publisher).on_action(action(2))
    ((subject, body, message_id),) = publisher.sent
    assert subject == f"executor.failed.sum.service.{RID}"
    assert body["data"]["reason"] == "Rejected" and body["data"]["retryable"] is False
    assert message_id == f"{ACTION_ID}.failed"


async def test_a_transient_failure_goes_back_to_the_queue_without_a_result() -> None:
    granter = FakeGranter(
        fail=ProviderError("ProviderUnavailable", retryable=True, detail="HTTP 503")
    )
    publisher = FakePublisher()
    with pytest.raises(TransientFailureError):
        await executor(granter, desired(2), publisher).on_action(action(2))
    assert publisher.sent == []


async def test_a_result_that_cannot_be_published_goes_back_to_the_queue() -> None:
    granter, publisher = FakeGranter(), FakePublisher(fail=True)
    with pytest.raises(TransientFailureError):
        await executor(granter, desired(2), publisher).on_action(action(2))
