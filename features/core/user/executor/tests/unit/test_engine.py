"""Motor do Executor: revalidação da action, desfecho prévio e publicação dos resultados."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from core_user_executor.contracts import generated
from core_user_executor.domain.errors import ActionFailedError
from core_user_executor.domain.identity import Grant, ProviderError, ZitadelUser
from core_user_executor.engine.executor import Disposition, Executor, PublishError
from core_user_executor.settings import ZitadelSettings

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
RESOURCE = "user-1"
ACTION_ID = f"{RESOURCE}.1.create.obs-1"


@dataclass
class FakePublisher:
    published: list[tuple[str, dict[str, Any]]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError
        self.published.append((subject, json.loads(payload)))


@dataclass
class FakeState:
    desired: dict[str, Any] | None = None
    results: dict[tuple[str, str], dict[str, Any]] = field(default_factory=lambda: {})

    async def last_desired(self, resource_id: str) -> dict[str, Any] | None:
        return self.desired

    async def last_result(
        self, resource_id: str, operation: str, kind: str
    ) -> dict[str, Any] | None:
        return self.results.get((operation, kind))


@dataclass
class FakeWriter:
    calls: list[str] = field(default_factory=lambda: [])
    error: Exception | None = None
    users: dict[str, ZitadelUser] = field(default_factory=lambda: {})

    async def get_user(self, user_id: str) -> ZitadelUser | None:
        return self.users.get(user_id)

    async def create_user(
        self, user_id: str, *, given_name: str, family_name: str, email: str
    ) -> bool:
        if self.error:
            raise self.error
        self.calls.append("create_user")
        return True

    async def send_password_link(self, user_id: str) -> None:
        self.calls.append("send_password_link")

    async def delete_user(self, user_id: str) -> None:
        if self.error:
            raise self.error
        self.calls.append("delete_user")

    async def grants(self, user_id: str) -> list[Grant]:
        return []

    async def create_grant(self, user_id: str, roles: list[str]) -> None:
        self.calls.append("create_grant")

    async def update_grant(self, user_id: str, grant_id: str, roles: list[str]) -> None:
        self.calls.append("update_grant")

    async def remove_grant(self, user_id: str, grant_id: str) -> None:
        self.calls.append("remove_grant")


def desired_message(
    *, generation: int = 1, lifecycle: str = "present", reconciliation: str = "active"
) -> dict[str, Any]:
    return {
        "desiredGeneration": generation,
        "data": {
            "lifecycle": lifecycle,
            "reconciliation": reconciliation,
            "platformAccess": "granted",
            "givenName": "Ana",
            "familyName": "Souza",
            "email": "ana@example.com",
        },
    }


def action(
    operation: str = "create", *, generation: int = 1, action_id: str = ACTION_ID, **fields: Any
) -> bytes:
    message: dict[str, Any] = {
        "messageId": "act-1",
        "schemaVersion": "1.0",
        "messageType": "action",
        "emitter": "reconciler",
        "module": "core",
        "resourceType": "user",
        "resourceId": RESOURCE,
        "operation": operation,
        "actionId": action_id,
        "desiredGeneration": generation,
        "requestedBy": "anonymous",
        "correlationId": "corr-1",
        "causationId": "obs-1",
        "occurredAt": NOW.isoformat(),
        "publishedAt": NOW.isoformat(),
        "data": {"reason": "Missing"},
    }
    message.update(fields)
    return json.dumps(message).encode()


def build(writer: FakeWriter, state: FakeState, publisher: FakePublisher) -> Executor:
    return Executor(
        writer, publisher, state, ZitadelSettings(), clock=lambda: NOW, identifiers=lambda: "msg-1"
    )


async def test_a_valid_create_executes_and_publishes_a_valid_completed() -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    state = FakeState(desired=desired_message())

    disposition = await build(writer, state, publisher).handle(action())

    assert disposition is Disposition.ACK
    assert writer.calls == ["create_user", "send_password_link", "create_grant"]
    ((subject, payload),) = publisher.published
    assert subject == f"executor.completed.core.user.{RESOURCE}.create"
    result = generated.MessageEnvelope.model_validate(payload)
    assert (result.emitter.value, result.message_type.value) == ("executor", "completed")
    assert (result.action_id, result.desired_generation) == (ACTION_ID, 1)
    assert result.causation_id == "act-1" and result.requested_by == "anonymous"
    assert result.data == {}


@pytest.mark.parametrize(
    ("state_desired", "operation", "reason"),
    [
        (desired_message(generation=2), "create", "StaleAction"),
        (None, "create", "StaleAction"),
        (desired_message(reconciliation="suspended"), "create", "Suspended"),
        (desired_message(lifecycle="absent"), "create", "Rejected"),
        (desired_message(lifecycle="present"), "delete", "Rejected"),
        (desired_message(), "reconcile", "Rejected"),
    ],
)
async def test_an_action_that_fails_revalidation_never_touches_the_provider(
    state_desired: dict[str, Any] | None, operation: str, reason: str
) -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    state = FakeState(desired=state_desired)

    await build(writer, state, publisher).handle(action(operation))

    assert writer.calls == []
    ((subject, payload),) = publisher.published
    assert subject.startswith("executor.failed.")
    assert payload["data"]["reason"] == reason and payload["data"]["retryable"] is False


async def test_a_completed_outcome_for_the_same_action_is_republished_without_executing() -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    state = FakeState(
        desired=desired_message(),
        results={("create", "completed"): {"actionId": ACTION_ID, "data": {}}},
    )
    await build(writer, state, publisher).handle(action())
    assert writer.calls == []
    assert publisher.published[0][0].startswith("executor.completed.")


async def test_a_permanent_failure_for_the_same_action_is_republished_without_executing() -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    previous = {
        "actionId": ACTION_ID,
        "data": {"reason": "Rejected", "retryable": False, "message": "x"},
    }
    state = FakeState(desired=desired_message(), results={("create", "failed"): previous})
    await build(writer, state, publisher).handle(action())
    assert writer.calls == []
    assert publisher.published[0][1]["data"]["reason"] == "Rejected"


async def test_a_retryable_failure_for_the_same_action_does_not_block_the_retry() -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    previous = {"actionId": ACTION_ID, "data": {"reason": "ProviderUnavailable", "retryable": True}}
    state = FakeState(desired=desired_message(), results={("create", "failed"): previous})
    await build(writer, state, publisher).handle(action())
    assert writer.calls  # executou de novo
    assert publisher.published[0][0].startswith("executor.completed.")


async def test_a_completed_outcome_of_another_action_does_not_block() -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    state = FakeState(
        desired=desired_message(),
        results={("create", "completed"): {"actionId": "outra", "data": {}}},
    )
    await build(writer, state, publisher).handle(action())
    assert writer.calls


@pytest.mark.parametrize(
    ("error", "reason", "retryable"),
    [
        (ProviderError("ProviderUnavailable", retryable=True), "ProviderUnavailable", True),
        (ProviderError("Unauthorized", retryable=False), "Unauthorized", False),
        (ActionFailedError("Rejected", retryable=False, message="x"), "Rejected", False),
    ],
)
async def test_provider_failures_become_failed_messages_and_are_acked(
    error: Exception, reason: str, retryable: bool
) -> None:
    writer, publisher = FakeWriter(error=error), FakePublisher()
    state = FakeState(desired=desired_message())

    disposition = await build(writer, state, publisher).handle(action())

    assert disposition is Disposition.ACK  # o retry é do Reconciler, e não da fila
    ((subject, payload),) = publisher.published
    assert subject == f"executor.failed.core.user.{RESOURCE}.create"
    result = generated.MessageEnvelope.model_validate(payload)
    assert result.data["reason"] == reason and result.data["retryable"] is retryable


async def test_delete_executes_for_an_absent_desired() -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    state = FakeState(desired=desired_message(lifecycle="absent"))
    await build(writer, state, publisher).handle(action("delete"))
    assert writer.calls == ["delete_user"]


async def test_a_publish_failure_propagates_so_the_action_returns_to_the_queue() -> None:
    writer, publisher = FakeWriter(), FakePublisher(fail=True)
    state = FakeState(desired=desired_message())
    with pytest.raises(PublishError):
        await build(writer, state, publisher).handle(action())


@pytest.mark.parametrize(
    "payload",
    [
        b"nao e json",
        b'{"messageId": "x"}',
        action(messageType="desired"),
        action(emitter="manager"),
        action(resourceType="organization"),
    ],
)
async def test_invalid_or_foreign_messages_are_terminated(payload: bytes) -> None:
    writer, publisher = FakeWriter(), FakePublisher()
    disposition = await build(writer, FakeState(desired=desired_message()), publisher).handle(
        payload
    )
    assert disposition is Disposition.TERM
    assert writer.calls == [] and publisher.published == []
