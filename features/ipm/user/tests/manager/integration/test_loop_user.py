"""Manager: `observed`, `completed` e `failed` contra o SSOT real (SSOT §10.2 e §10.3)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from support_manager import (
    DEFAULT_DIGEST,
    Cleanup,
    fetch_all,
    fetch_one,
    requested_message,
    ssot,
    unique_suffix,
)

from ipm_user.manager.domain.errors import PermanentMessageError
from ipm_user.manager.domain.kind import USER
from ipm_user.manager.domain.outcome import OutcomeKind
from ipm_user.manager.handlers.observed import ObservedHandler
from ipm_user.manager.handlers.requested import RequestedHandler
from ipm_user.manager.handlers.result import ResultHandler

Connection = psycopg.AsyncConnection[Any]
requested_handler = RequestedHandler()
observed_handler = ObservedHandler()
BASE_TIME = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def granted(message: dict[str, Any]) -> dict[str, Any]:
    """O que o Observer leria no Zitadel quando o usuário já converge para o desejado."""
    return {
        "emailVerified": True,
        "userState": "active",
        "roles": message["data"]["specification"]["roles"],
        "deletionProtection": False,
    }


def register(cleanup: Cleanup) -> dict[str, Any]:
    return requested_message(
        resource_type="user",
        resource_id=cleanup.track(str(uuid.uuid7())),
        operation="create",
        requested_by="owner-1",
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "specification": {
                "organizationId": "org-1",
                "givenName": "Bia",
                "familyName": "Lima",
                "email": f"loop-{unique_suffix()}@example.com",
                "roles": ["ipm.user.get"],
                "deletionProtection": False,
            },
        },
    )


def observed(
    resource_id: str,
    presence: str,
    *,
    seconds: int,
    data: dict[str, Any] | None = None,
    generation: int | None = 1,
) -> dict[str, Any]:
    """`generation`: a geração que o Observer conhecia antes de ler o provedor (decisão 0072)."""
    moment = (BASE_TIME + timedelta(seconds=seconds)).isoformat()
    return {
        "messageId": str(uuid.uuid7()),
        "schemaVersion": "1.0",
        "messageType": "observed",
        "emitter": "observer",
        "module": "ipm",
        "resourceType": "user",
        "resourceId": resource_id,
        "operation": "changed",
        "presence": presence,
        "observedAt": moment,
        **({"observedGeneration": generation} if generation is not None else {}),
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
        "module": "ipm",
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
        " failure_count, conditions FROM ipm.user WHERE resource_id = %s",
        resource_id,
    )


async def operation_status(connection: Connection, resource_id: str) -> list[str]:
    rows = await fetch_all(
        connection,
        "SELECT operation_status FROM ipm.user_operation WHERE resource_id = %s"
        " ORDER BY created_at",
        resource_id,
    )
    return [item["operation_status"] for item in rows]


async def outbox_types(outbox_reader: Connection, resource_id: str) -> list[str]:
    rows = await fetch_all(
        outbox_reader,
        "SELECT subject FROM ipm.user_outbox WHERE resource_id = %s ORDER BY sequence",
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
    message = await created(cleanup, user_manager)
    resource_id = message["resourceId"]
    await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "absent", seconds=1)
    )

    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=2, data=granted(message)),
    )

    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert (stored["phase"], stored["conditions"][0]["status"]) == ("Ready", "True")
    assert stored["observed"] == granted(message)
    assert await operation_status(user_manager, resource_id) == ["completed"]


async def test_present_without_platform_access_is_not_converged(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    resource_id = (await created(cleanup, user_manager))["resourceId"]
    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(
            resource_id,
            "present",
            seconds=1,
            data={"emailVerified": True, "userState": "active", "roles": []},
        ),
    )
    stored = await row(user_manager, resource_id)
    assert stored is not None
    assert stored["phase"] == "Reconciling"


async def test_older_or_equal_observation_is_ignored_and_unknown_does_not_change_phase(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    message = await created(cleanup, user_manager)
    resource_id = message["resourceId"]
    await observed_handler.handle(
        ssot(user_manager), USER, observed(resource_id, "absent", seconds=10)
    )

    stale = await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=5, data=granted(message)),
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


async def test_observation_of_an_unknown_resource_is_ignored(
    user_manager: Connection,
) -> None:
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
        observed(resource_id, "present", seconds=1, data=granted(message)),
    )
    # Desprotegido por padrão (decisão 0077): a remoção vai direto.
    stored = await row(user_manager, resource_id)
    assert stored is not None
    delete = requested_message(
        resource_type="user",
        resource_id=resource_id,
        operation="delete",
        requested_by="owner-1",
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
        ssot(user_manager),
        USER,
        observed(resource_id, "absent", seconds=3, generation=2),
    )

    assert await row(user_manager, resource_id) is None
    assert await operation_status(user_manager, resource_id) == ["completed", "completed"]
    last = (
        await fetch_all(
            outbox_reader,
            "SELECT payload FROM ipm.user_outbox WHERE resource_id = %s"
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
            "SELECT payload FROM ipm.user_outbox WHERE resource_id = %s AND subject LIKE %s"
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
        {"resourceType": "account"},
    ],
)
async def test_a_message_that_is_not_an_executor_result_is_permanently_invalid(
    user_manager: Connection, bad: dict[str, Any]
) -> None:
    message = {**result(str(uuid.uuid7()), "completed", generation=1), **bad}
    with pytest.raises(PermanentMessageError):
        await ResultHandler().handle(ssot(user_manager), USER, message)


async def updated_generations(outbox_reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        outbox_reader,
        "SELECT payload FROM ipm.user_outbox WHERE resource_id = %s"
        " AND subject LIKE 'manager.updated.%%' ORDER BY sequence",
        resource_id,
    )
    return [
        {
            key: item["payload"]["data"].get(key)
            for key in ("desiredGeneration", "observedGeneration")
        }
        for item in rows
    ]


async def test_protection_change_completes_only_on_the_observation_of_its_generation(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    """Mesmo fluxo de qualquer alteração: requested → desired → observed → updated (decisão 0072).

    Uma leitura feita antes da nova geração não a confirma, mesmo com o conteúdo igual: só uma
    observação feita depois da nova geração conclui a Operation.
    """
    message = await created(cleanup, user_manager)
    resource_id = message["resourceId"]
    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(resource_id, "present", seconds=1, data=granted(message)),
    )
    converged = await row(user_manager, resource_id)
    assert converged is not None and converged["phase"] == "Ready"

    unprotect = requested_message(
        resource_type="user",
        resource_id=resource_id,
        operation="update",
        requested_by="owner-1",
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "resourceVersion": str(converged["resource_version"]),
            "specification": {"deletionProtection": True},
        },
    )
    outcome = await requested_handler.handle(ssot(user_manager), USER, unprotect)
    assert outcome.kind is OutcomeKind.ACCEPTED
    pending = await row(user_manager, resource_id)
    assert pending is not None and pending["phase"] == "Reconciling"
    assert await operation_status(user_manager, resource_id) == ["completed", "accepted"]

    # Leitura feita antes da geração 2 (conteúdo igual): não confirma a geração nova.
    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(
            resource_id,
            "present",
            seconds=2,
            data={**granted(message), "deletionProtection": True},
            generation=1,
        ),
    )
    stale = await row(user_manager, resource_id)
    assert stale is not None and stale["phase"] == "Reconciling"
    assert await operation_status(user_manager, resource_id) == ["completed", "in_progress"]

    # Observação feita depois da geração 2: conclui.
    await observed_handler.handle(
        ssot(user_manager),
        USER,
        observed(
            resource_id,
            "present",
            seconds=3,
            data={**granted(message), "deletionProtection": True},
            generation=2,
        ),
    )
    done = await row(user_manager, resource_id)
    assert done is not None and done["phase"] == "Ready"
    assert await operation_status(user_manager, resource_id) == ["completed", "completed"]
    assert await updated_generations(outbox_reader, resource_id) == [
        {"desiredGeneration": 1, "observedGeneration": 1},
        {"desiredGeneration": 2, "observedGeneration": 1},
        {"desiredGeneration": 2, "observedGeneration": 2},
    ]
