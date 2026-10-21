import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sum_service.common.logging_config import bind_traceparent, current_traceparent
from sum_service.reconciler.engine.reconciler import PublishError, Reconciler
from sum_service.reconciler.settings import LoopSettings

NOW = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
RID = "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b"
OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
ROLES = ["ipm.organization.get", "ipm.organization.list"]


@dataclass
class Recorder:
    sent: list[tuple[str, dict[str, Any], str]] = field(default_factory=lambda: [])
    fail: bool = False

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        if self.fail:
            raise PublishError("down")
        self.sent.append((subject, json.loads(payload), message_id))


def envelope(message_type: str, emitter: str, message_id: str, **fields: Any) -> bytes:
    base: dict[str, Any] = {
        "messageId": message_id,
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": emitter,
        "module": "sum",
        "resourceType": "service",
        "resourceId": RID,
        "operation": "changed",
        "occurredAt": "2026-10-15T14:00:00Z",
        "publishedAt": "2026-10-15T14:00:00Z",
        "publishedBy": "sum-service-publisher",
        "data": {},
    }
    base.update(fields)
    return json.dumps(base).encode()


def desired(
    generation: int,
    lifecycle: str = "present",
    roles: list[str] = ROLES,
    message_id: str = "m-desired",
) -> bytes:
    return envelope(
        "desired",
        "manager",
        message_id,
        desiredGeneration=generation,
        requestedBy=OWNER,
        correlationId="0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1c",
        data={
            "lifecycle": lifecycle,
            "reconciliation": "active",
            "ownerAccountId": OWNER,
            "service": "ipm",
            "serviceRoles": roles,
        },
    )


def observed(
    roles: list[str], message_id: str, at: datetime = NOW, causation: str | None = None
) -> bytes:
    fields: dict[str, Any] = {
        "presence": "present",
        "observedAt": at.isoformat(),
        "data": {"serviceRoles": roles},
    }
    if causation:
        fields["causationId"] = causation
    return envelope("observed", "observer", message_id, **fields)


def result(message_type: str, action_id: str, generation: int, message_id: str) -> bytes:
    return envelope(
        message_type, "executor", message_id, actionId=action_id, desiredGeneration=generation
    )


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def engine(publisher: Recorder, clock: datetime = NOW) -> Reconciler:
    ids = iter(f"id-{n}" for n in range(1, 1000))
    return Reconciler(publisher, LoopSettings(), clock=lambda: clock, identifiers=lambda: next(ids))


async def test_a_missing_role_publishes_one_update_with_the_action_identity() -> None:
    recorder = Recorder()
    reconciler = engine(recorder)
    await reconciler.on_message(desired(1))
    await reconciler.on_message(observed([], "m-observed"))
    assert len(recorder.sent) == 1
    subject, body, message_id = recorder.sent[0]
    assert subject == f"reconciler.action.sum.service.{RID}.update"
    assert message_id == f"{RID}.1.update.m-observed"  # Nats-Msg-Id = actionId
    assert body["messageType"] == "action" and body["data"]["reason"] == "Drift"


async def test_an_observation_with_the_roles_publishes_nothing() -> None:
    recorder = Recorder()
    reconciler = engine(recorder)
    await reconciler.on_message(desired(1))
    await reconciler.on_message(observed(ROLES, "m-observed"))
    assert recorder.sent == []


async def test_a_pending_action_is_not_emitted_again_before_its_result() -> None:
    recorder = Recorder()
    reconciler = engine(recorder)
    await reconciler.on_message(desired(1))
    await reconciler.on_message(observed([], "m-observed"))
    await reconciler.on_message(observed([], "m-observed-2", at=NOW + timedelta(seconds=1)))
    assert len(recorder.sent) == 1


async def test_a_completed_action_without_effect_backs_off_before_the_next_decision(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Uma ação que conclui sem mudar o recurso não se repete sem freio (decisão 0078)."""
    recorder = Recorder()
    clock = Clock(NOW)
    reconciler = Reconciler(
        recorder,
        LoopSettings(),
        clock=clock,
        identifiers=iter(f"id-{n}" for n in range(99)).__next__,
    )
    await reconciler.on_message(desired(1))
    await reconciler.on_message(observed([], "m-observed"))
    action_id = recorder.sent[0][2]
    await reconciler.on_message(result("completed", action_id, 1, "m-result"))
    # Ainda sem a observação causada pelo resultado: nada a decidir.
    await reconciler.on_message(observed([], "m-observed-2", at=NOW + timedelta(seconds=1)))
    assert len(recorder.sent) == 1
    # A observação causada chega e o usuário ainda não tem a role: a ação não teve efeito.
    with caplog.at_level(logging.WARNING):
        await reconciler.on_message(
            observed([], "m-observed-3", at=NOW + timedelta(seconds=2), causation="m-result")
        )
    assert len(recorder.sent) == 1  # em backoff
    warning = next(r for r in caplog.records if r.getMessage() == "action had no effect")
    assert warning.__dict__["smarkee.drift.fields"] == ["serviceRoles"]
    # Passado o backoff (30 s na primeira, `failure_backoff_seconds`), a decisão volta.
    clock.now = NOW + timedelta(seconds=40)
    await reconciler.on_message(observed([], "m-observed-4", at=NOW + timedelta(seconds=39)))
    assert len(recorder.sent) == 2
    assert recorder.sent[1][1]["data"]["reason"] == "Drift"


async def test_a_refused_publication_is_retried_on_the_next_message() -> None:
    recorder = Recorder(fail=True)
    reconciler = engine(recorder)
    await reconciler.on_message(desired(1))
    await reconciler.on_message(observed([], "m-observed"))
    assert recorder.sent == []
    recorder.fail = False
    await reconciler.on_message(observed([], "m-observed-2", at=NOW + timedelta(seconds=1)))
    assert len(recorder.sent) == 1


async def test_a_disabled_link_with_roles_publishes_the_removal() -> None:
    recorder = Recorder()
    reconciler = engine(recorder)
    await reconciler.on_message(desired(2, lifecycle="absent", roles=[]))
    await reconciler.on_message(observed(ROLES, "m-observed"))
    assert recorder.sent[0][1]["data"]["reason"] == "RolesRemovalRequested"


async def test_an_envelope_of_another_module_is_ignored() -> None:
    recorder = Recorder()
    reconciler = engine(recorder)
    other = json.loads(desired(1))
    other["module"] = "core"
    assert await reconciler.on_message(json.dumps(other).encode()) is None
    assert recorder.sent == []


TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


async def test_the_action_inherits_the_trace_of_the_desired_even_if_the_observation_has_none() -> (
    None
):
    contexts: list[str | None] = []

    class TracingRecorder(Recorder):
        async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
            contexts.append(current_traceparent())
            await super().publish(subject, payload, message_id=message_id)

    reconciler = engine(TracingRecorder())
    bind_traceparent(TRACEPARENT)  # contexto do consumo do `desired`
    await reconciler.on_message(desired(1))
    bind_traceparent(None)  # a observação chega sem contexto
    await reconciler.on_message(observed([], "m-observed"))

    assert contexts == [TRACEPARENT]
    assert current_traceparent() is None  # o contexto da action não vaza para o próximo evento
