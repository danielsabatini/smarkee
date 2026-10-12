"""Manager: `observed`, `completed` e `failed` de User contra o SSOT real (SSOT.md §10.2, §10.3)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from support import (
    DEFAULT_DIGEST,
    Cleanup,
    fetch_all,
    fetch_one,
    requested_message,
    ssot,
    unique_suffix,
)

from core_user_manager.domain.errors import PermanentMessageError
from core_user_manager.domain.kind import USER
from core_user_manager.domain.outcome import OutcomeKind
from core_user_manager.handlers.observed import ObservedHandler
from core_user_manager.handlers.requested import RequestedHandler
from core_user_manager.handlers.result import ResultHandler

Connection = psycopg.AsyncConnection[Any]
requested_handler = RequestedHandler()
observed_handler = ObservedHandler()
BASE_TIME = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def register(cleanup: Cleanup) -> dict[str, Any]:
    return requested_message(
        resource_type="user",
        resource_id=cleanup.track(str(uuid.uuid7())),
        operation="create",
        requested_by="anonymous",
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "specification": {
                "givenName": "Ana",
                "familyName": "Souza",
                "email": f"loop.{unique_suffix()}@example.com",
            },
        },
    )


def observed(
    resource_id: str, presence: str, *, seconds: int, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    moment = (BASE_TIME + timedelta(seconds=seconds)).isoformat()
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "observed",
        "emitter": "observer",
        "module": "core",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": "changed",
        "presence": presence,
        "observedAt": moment,
        "correlationId": str(uuid.uuid7()),
        "occurredAt": moment,
        "publishedAt": moment,
        "data": data or {},
    }


def result(
    resource_id: str,
    message_type: str,
    *,
    generation: int,
    action_id: str | None = None,
    data: dict[str, Any] | None = None,
    operation: str = "create",
) -> dict[str, Any]:
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": message_type,
        "emitter": "executor",
        "module": "core",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": operation,
        "actionId": action_id or f"{resource_id}.{generation}.{operation}.{uuid.uuid4().hex[:6]}",
        "desiredGeneration": generation,
        "causationId": str(uuid.uuid7()),
        "correlationId": str(uuid.uuid7()),
        "occurredAt": BASE_TIME.isoformat(),
        "publishedAt": BASE_TIME.isoformat(),
        "data": data
        or (
            {}
            if message_type == "completed"
            else {"reason": "ProviderUnavailable", "retryable": True}
        ),
    }


async def row(connection: Connection, resource_id: str) -> dict[str, Any] | None:
    return await fetch_one(
        connection,
        "SELECT resource_version, lifecycle, reconciliation, phase, presence, observed,"
        ' failure_count, conditions FROM core."user" WHERE resource_id = %s',
        resource_id,
    )


async def operation_status(connection: Connection, resource_id: str) -> list[str]:
    rows = await fetch_all(
        connection,
        "SELECT operation_status FROM core.user_operation WHERE resource_id = %s"
        " ORDER BY created_at",
        resource_id,
    )
    return [item["operation_status"] for item in rows]


async def outbox_types(outbox_reader: Connection, resource_id: str) -> list[str]:
    rows = await fetch_all(
        outbox_reader,
        "SELECT subject FROM core.user_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )
    return [item["subject"].split(".")[1] for item in rows]


async def created(cleanup: Cleanup, manager: Connection) -> dict[str, Any]:
    message = register(cleanup)
    await requested_handler.handle(ssot(manager), USER, message)
    return message


async def test_absent_observation_moves_to_reconciling_and_keeps_the_operation_open(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    message = await created(cleanup, user_manager)
    resource_id = message["resourceId"]

    outcome = await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "absent", seconds=1)
    )

    assert outcome.kind is OutcomeKind.APPLIED
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["phase"], stored["presence"], stored["resource_version"]) == (
        "Reconciling",
        "absent",
        2,
    )
    assert stored["conditions"][0]["type"] == "Ready"
    assert stored["conditions"][0]["status"] == "False"
    assert await operation_status(user_manager, resource_id) == ["in_progress"]
    assert await outbox_types(outbox_reader, resource_id) == ["desired", "updated"]


async def test_converged_observation_is_ready_and_completes_the_operation(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "absent", seconds=1)
    )

    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=2, data={"platformAccess": "granted"}),
    )

    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["phase"], stored["conditions"][0]["status"]) == ("Ready", "True")
    assert stored["observed"] == {"platformAccess": "granted"}
    assert await operation_status(user_manager, resource_id) == ["completed"]


async def test_present_without_platform_access_is_not_converged(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=1, data={"platformAccess": "revoked"}),
    )
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert stored["phase"] == "Reconciling"


async def test_older_or_equal_observation_is_ignored_and_unknown_does_not_change_phase(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "absent", seconds=10)
    )

    stale = await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=5, data={"platformAccess": "granted"}),
    )
    assert stale.kind is OutcomeKind.IGNORED
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["phase"], stored["presence"]) == ("Reconciling", "absent")

    unknown = await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "unknown", seconds=20)
    )
    assert unknown.kind is OutcomeKind.APPLIED
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["phase"], stored["presence"]) == ("Reconciling", "unknown")


async def test_observation_of_an_unknown_resource_is_ignored(user_manager: Connection) -> None:
    outcome = await observed_handler.handle(
        ssot(user_manager), USER, observed(str(uuid.uuid7()), "absent", seconds=1)
    )
    assert outcome.kind is OutcomeKind.IGNORED


async def test_removal_converged_deletes_the_record_and_publishes_removed(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    message = await created(cleanup, user_manager)
    resource_id = message["resourceId"]
    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=1, data={"platformAccess": "granted"}),
    )
    stored = await row(user_manager, resource_id)
    assert stored is not None
    delete = requested_message(
        resource_type="user",
        resource_id=resource_id,
        operation="delete",
        requested_by=resource_id,
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "resourceVersion": str(stored["resource_version"]),
        },
    )
    await requested_handler.handle(ssot(user_manager), USER, delete)
    during = await row(user_manager, resource_id)
    assert during is not None and during["phase"] == "Deleting"

    await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "absent", seconds=2)
    )

    assert await row(user_manager, resource_id) is None
    assert await operation_status(user_manager, resource_id) == ["completed", "completed"]
    last = (
        await fetch_all(
            outbox_reader,
            "SELECT payload FROM core.user_outbox WHERE resource_id = %s"
            " ORDER BY sequence DESC LIMIT 1",
            resource_id,
        )
    )[0]["payload"]
    assert last["data"]["removed"] is True


async def test_failures_are_counted_and_the_limit_suspends_reconciliation(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    results = ResultHandler(failure_limit=2)

    first = await results.handle(
        ssot(user_manager), USER, result(resource_id, "failed", generation=1)
    )
    assert first.kind is OutcomeKind.APPLIED
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["failure_count"], stored["phase"], stored["reconciliation"]) == (
        1,
        "Reconciling",
        "active",
    )

    await results.handle(ssot(user_manager), USER, result(resource_id, "failed", generation=1))
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["failure_count"], stored["phase"], stored["reconciliation"]) == (
        2,
        "Failed",
        "suspended",
    )
    assert await operation_status(user_manager, resource_id) == ["failed"]
    suspended = (
        await fetch_all(
            outbox_reader,
            "SELECT payload FROM core.user_outbox WHERE resource_id = %s AND subject LIKE %s"
            " ORDER BY sequence DESC LIMIT 1",
            resource_id,
            "manager.desired.%",
        )
    )[0]["payload"]
    assert (suspended["desiredGeneration"], suspended["data"]["reconciliation"]) == (1, "suspended")


async def test_a_result_is_counted_only_once_per_action(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    results = ResultHandler(failure_limit=5)
    message = result(resource_id, "failed", generation=1, action_id=f"{resource_id}.1.create.dup")

    assert (await results.handle(ssot(user_manager), USER, message)).kind is OutcomeKind.APPLIED
    assert (await results.handle(ssot(user_manager), USER, message)).kind is OutcomeKind.DUPLICATE

    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert stored["failure_count"] == 1


async def test_a_result_of_a_superseded_generation_does_not_change_the_resource(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    outcome = await ResultHandler(failure_limit=1).handle(
        ssot(user_manager), USER, result(resource_id, "failed", generation=7)
    )
    assert outcome.kind is OutcomeKind.IGNORED
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["failure_count"], stored["phase"]) == (0, "Pending")


async def test_a_completed_result_does_not_count_a_failure(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    await ResultHandler().handle(
        ssot(user_manager), USER, result(resource_id, "completed", generation=1)
    )
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["failure_count"], stored["phase"]) == (0, "Reconciling")
    assert stored["conditions"][0]["reason"] == "Reconciling"


@pytest.mark.parametrize(
    "bad",
    [
        {"messageType": "desired"},
        {"emitter": "manager"},
        {"resourceType": "organization"},
    ],
)
async def test_a_message_that_is_not_an_executor_result_is_permanently_invalid(
    user_manager: Connection, bad: dict[str, Any]
) -> None:
    message = {**result(str(uuid.uuid7()), "completed", generation=1), **bad}
    with pytest.raises(PermanentMessageError):
        await ResultHandler().handle(ssot(user_manager), USER, message)
