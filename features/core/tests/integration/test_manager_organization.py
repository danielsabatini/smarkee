"""Manager: `requested` de Organization contra o SSOT real (docs/SSOT.md §10.1)."""

import asyncio
import uuid
from typing import Any

import psycopg
import pytest
from support import (
    DEFAULT_DIGEST,
    Cleanup,
    fetch_all,
    fetch_one,
    requested_message,
    unique_suffix,
)

from core.contracts import generated
from core.manager.errors import PermanentMessageError
from core.manager.kinds import ORGANIZATION
from core.manager.outcome import OutcomeKind, RejectionReason
from core.manager.requested import RequestedHandler

handler = RequestedHandler()
Connection = psycopg.AsyncConnection[Any]


def create_message(
    cleanup: Cleanup,
    *,
    owner: str,
    name: str | None = None,
    quota: int | None = None,
    operation_id: str | None = None,
    resource_id: str | None = None,
    digest: str = DEFAULT_DIGEST,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "operationId": operation_id or str(uuid.uuid7()),
        "requestDigest": digest,
        "specification": {"name": name or f"org-{unique_suffix()}", "platformAccess": "granted"},
    }
    if quota is not None:
        data["ownerQuotaLimit"] = quota
    return requested_message(
        resource_type="organization",
        resource_id=cleanup.track(resource_id or str(uuid.uuid7())),
        operation="create",
        requested_by=owner,
        data=data,
    )


def change_message(
    cleanup: Cleanup, *, create: dict[str, Any], operation: str, version: str, **data: Any
) -> dict[str, Any]:
    return requested_message(
        resource_type="organization",
        resource_id=cleanup.track(create["resourceId"]),
        operation=operation,
        requested_by=create["requestedBy"],
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "resourceVersion": version,
            **data,
        },
    )


async def resource_row(connection: Connection, resource_id: str) -> dict[str, Any] | None:
    return await fetch_one(
        connection,
        "SELECT resource_version, desired_generation, lifecycle, reconciliation, desired, phase,"
        " failure_count FROM core.organization WHERE resource_id = %s",
        resource_id,
    )


async def outbox(relay: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        relay,
        "SELECT subject, payload FROM core.organization_outbox"
        " WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_create_is_accepted_and_publishes_desired(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    message = create_message(cleanup, owner="user-1", name="acme-" + unique_suffix())
    outcome = await handler.handle(organization_manager, ORGANIZATION, message)

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(organization_manager, message["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["phase"]) == (1, 1, "Pending")
    assert row["lifecycle"] == "present"
    assert row["reconciliation"] == "active"
    assert row["desired"] == {
        "lifecycle": "present",
        "name": message["data"]["specification"]["name"],
        "platformAccess": "granted",
        "ownerUserId": "user-1",
    }

    operations = await fetch_all(
        organization_manager,
        "SELECT operation_status, operation_type, desired_generation, requested_by, request_digest"
        " FROM core.organization_operation WHERE operation_id = %s",
        message["data"]["operationId"],
    )
    assert [dict(item) for item in operations] == [
        {
            "operation_status": "accepted",
            "operation_type": "create",
            "desired_generation": 1,
            "requested_by": "user-1",
            "request_digest": DEFAULT_DIGEST,
        }
    ]

    published = await outbox(relay, message["resourceId"])
    assert len(published) == 1
    assert published[0]["subject"] == (
        f"manager.desired.core.organization.{message['resourceId']}.changed"
    )
    envelope = generated.MessageEnvelope.model_validate(published[0]["payload"])
    assert envelope.message_type.value == "desired"
    assert envelope.emitter.value == "manager"
    assert envelope.desired_generation == 1
    assert envelope.requested_by == "user-1"
    assert envelope.correlation_id == message["correlationId"]
    assert envelope.causation_id == message["messageId"]
    assert envelope.data == {
        "lifecycle": "present",
        "reconciliation": "active",
        "name": message["data"]["specification"]["name"],
        "platformAccess": "granted",
        "ownerUserId": "user-1",
    }


async def test_redelivery_is_ignored_without_new_writes(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    message = create_message(cleanup, owner="user-1")
    assert (await handler.handle(organization_manager, ORGANIZATION, message)).kind is (
        OutcomeKind.ACCEPTED
    )
    second = await handler.handle(organization_manager, ORGANIZATION, message)

    assert second.kind is OutcomeKind.DUPLICATE
    assert not second.digest_mismatch
    assert len(await outbox(relay, message["resourceId"])) == 1


async def test_same_operation_with_other_digest_is_flagged_and_original_prevails(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    first = create_message(cleanup, owner="user-1", digest="a" * 64)
    other = create_message(
        cleanup,
        owner="user-1",
        operation_id=first["data"]["operationId"],
        digest="b" * 64,
    )
    await handler.handle(organization_manager, ORGANIZATION, first)
    outcome = await handler.handle(organization_manager, ORGANIZATION, other)

    assert outcome.kind is OutcomeKind.DUPLICATE
    assert outcome.digest_mismatch
    assert await resource_row(organization_manager, other["resourceId"]) is None


@pytest.mark.parametrize("name", ["core", "smarkee"])
async def test_reserved_name_is_rejected_without_changing_anything(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection, name: str
) -> None:
    message = create_message(cleanup, owner="user-1", name=name)
    outcome = await handler.handle(organization_manager, ORGANIZATION, message)

    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert await resource_row(organization_manager, message["resourceId"]) is None
    assert await outbox(relay, message["resourceId"]) == []
    recorded = await fetch_one(
        organization_manager,
        "SELECT operation_status, operation_status_reason, desired_generation"
        " FROM core.organization_operation WHERE operation_id = %s",
        message["data"]["operationId"],
    )
    assert recorded == {
        "operation_status": "rejected",
        "operation_status_reason": "validation",
        "desired_generation": None,
    }


async def test_duplicate_name_is_rejected(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    name = "dup-" + unique_suffix()
    first = create_message(cleanup, owner="user-1", name=name)
    second = create_message(cleanup, owner="user-2", name=name)
    assert (await handler.handle(organization_manager, ORGANIZATION, first)).kind is (
        OutcomeKind.ACCEPTED
    )
    outcome = await handler.handle(organization_manager, ORGANIZATION, second)
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)


async def test_owner_quota_blocks_the_second_organization_of_the_same_owner(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    owner = "quota-" + unique_suffix()
    first = await handler.handle(
        organization_manager, ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
    )
    blocked = await handler.handle(
        organization_manager, ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
    )
    other_owner = await handler.handle(
        organization_manager,
        ORGANIZATION,
        create_message(cleanup, owner="quota-" + unique_suffix(), quota=1),
    )
    unlimited = await handler.handle(
        organization_manager, ORGANIZATION, create_message(cleanup, owner=owner)
    )

    assert first.kind is OutcomeKind.ACCEPTED
    assert (blocked.kind, blocked.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert other_owner.kind is OutcomeKind.ACCEPTED
    assert unlimited.kind is OutcomeKind.ACCEPTED  # sem limite (operador)


async def test_concurrent_creates_respect_quota_and_name_uniqueness(
    cleanup: Cleanup, organization_manager: Connection, organization_manager_2: Connection
) -> None:
    owner = "race-" + unique_suffix()
    results = await asyncio.gather(
        handler.handle(
            organization_manager, ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
        ),
        handler.handle(
            organization_manager_2, ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
        ),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]

    name = "race-name-" + unique_suffix()
    results = await asyncio.gather(
        handler.handle(
            organization_manager,
            ORGANIZATION,
            create_message(cleanup, owner="a-" + owner, name=name),
        ),
        handler.handle(
            organization_manager_2,
            ORGANIZATION,
            create_message(cleanup, owner="b-" + owner, name=name),
        ),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]


async def test_update_bumps_generation_and_version_and_publishes(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(organization_manager, ORGANIZATION, create)
    new_name = "renamed-" + unique_suffix()
    outcome = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="1",
            specification={"name": new_name},
        ),
    )

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["phase"]) == (
        2,
        2,
        "Reconciling",
    )
    assert row["desired"]["name"] == new_name
    messages = await outbox(relay, create["resourceId"])
    assert [item["payload"]["desiredGeneration"] for item in messages] == [1, 2]


async def test_stale_resource_version_is_a_conflict(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(organization_manager, ORGANIZATION, create)
    outcome = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="7",
            specification={"name": "x-" + unique_suffix()},
        ),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.CONFLICT)
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(relay, create["resourceId"])) == 1


async def test_unknown_resource_is_not_found(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    ghost = create_message(cleanup, owner="user-1")
    outcome = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(cleanup, create=ghost, operation="delete", version="1"),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.NOT_FOUND)


async def test_update_without_effective_change_completes_without_new_generation(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(organization_manager, ORGANIZATION, create)
    outcome = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="1",
            specification={"name": create["data"]["specification"]["name"]},
        ),
    )
    assert outcome.kind is OutcomeKind.COMPLETED
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(relay, create["resourceId"])) == 1


async def test_reconciliation_change_alone_keeps_generation(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(organization_manager, ORGANIZATION, create)
    outcome = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(
            cleanup, create=create, operation="update", version="1", reconciliation="suspended"
        ),
    )
    assert outcome.kind is OutcomeKind.COMPLETED
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["reconciliation"]) == (
        2,
        1,
        "suspended",
    )
    messages = await outbox(relay, create["resourceId"])
    assert [item["payload"]["data"]["reconciliation"] for item in messages] == [
        "active",
        "suspended",
    ]


async def test_delete_declares_absence_and_is_idempotent(
    cleanup: Cleanup, organization_manager: Connection, relay: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(organization_manager, ORGANIZATION, create)
    deleted = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(cleanup, create=create, operation="delete", version="1"),
    )
    assert deleted.kind is OutcomeKind.ACCEPTED
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["lifecycle"], row["phase"], row["desired_generation"]) == ("absent", "Deleting", 2)

    repeated = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(cleanup, create=create, operation="delete", version="2"),
    )
    assert repeated.kind is OutcomeKind.COMPLETED
    after = await handler.handle(
        organization_manager,
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="2",
            specification={"name": "z-" + unique_suffix()},
        ),
    )
    assert (after.kind, after.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert len(await outbox(relay, create["resourceId"])) == 2


async def test_invalid_message_is_a_permanent_error(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    broken = create_message(cleanup, owner="user-1")
    broken["data"]["specification"]["name"] = "Nome Inválido!"
    with pytest.raises(PermanentMessageError, match="requested/create"):
        await handler.handle(organization_manager, ORGANIZATION, broken)

    wrong_emitter = create_message(cleanup, owner="user-1")
    wrong_emitter["emitter"] = "manager"
    with pytest.raises(PermanentMessageError, match="não é um requested da API"):
        await handler.handle(organization_manager, ORGANIZATION, wrong_emitter)
