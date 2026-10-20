"""Manager: `requested` de Organization contra o SSOT real (docs/SSOT.md §10.1)."""

import asyncio
import uuid
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

from ipm_organization.common.contracts import generated
from ipm_organization.manager.domain.errors import PermanentMessageError
from ipm_organization.manager.domain.kind import ORGANIZATION
from ipm_organization.manager.domain.organization import RESERVED_ORGANIZATION_NAMES
from ipm_organization.manager.domain.outcome import OutcomeKind, RejectionReason
from ipm_organization.manager.handlers.requested import RequestedHandler

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
        " failure_count FROM ipm.organization WHERE resource_id = %s",
        resource_id,
    )


async def outbox(outbox_reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        outbox_reader,
        "SELECT subject, payload FROM ipm.organization_outbox"
        " WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_create_is_accepted_and_publishes_desired(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup, owner="user-1", name="acme-" + unique_suffix())
    outcome = await handler.handle(ssot(organization_manager), ORGANIZATION, message)

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
        "ownerAccountId": "user-1",
        "deletionProtection": True,
    }

    operations = await fetch_all(
        organization_manager,
        "SELECT operation_status, operation_type, desired_generation, requested_by, request_digest"
        " FROM ipm.organization_operation WHERE operation_id = %s",
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

    published = await outbox(outbox_reader, message["resourceId"])
    assert len(published) == 1
    assert published[0]["subject"] == (
        f"manager.desired.ipm.organization.{message['resourceId']}.changed"
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
        "ownerAccountId": "user-1",
        "deletionProtection": True,
    }


async def test_redelivery_is_ignored_without_new_writes(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup, owner="user-1")
    assert (await handler.handle(ssot(organization_manager), ORGANIZATION, message)).kind is (
        OutcomeKind.ACCEPTED
    )
    second = await handler.handle(ssot(organization_manager), ORGANIZATION, message)

    assert second.kind is OutcomeKind.DUPLICATE
    assert not second.digest_mismatch
    assert len(await outbox(outbox_reader, message["resourceId"])) == 1


async def test_same_operation_with_other_digest_is_flagged_and_original_prevails(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    first = create_message(cleanup, owner="user-1", digest="a" * 64)
    other = create_message(
        cleanup,
        owner="user-1",
        operation_id=first["data"]["operationId"],
        digest="b" * 64,
    )
    await handler.handle(ssot(organization_manager), ORGANIZATION, first)
    outcome = await handler.handle(ssot(organization_manager), ORGANIZATION, other)

    assert outcome.kind is OutcomeKind.DUPLICATE
    assert outcome.digest_mismatch
    assert await resource_row(organization_manager, other["resourceId"]) is None


@pytest.mark.parametrize("name", sorted(RESERVED_ORGANIZATION_NAMES))
async def test_reserved_name_is_rejected_without_changing_anything(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection, name: str
) -> None:
    message = create_message(cleanup, owner="user-1", name=name)
    outcome = await handler.handle(ssot(organization_manager), ORGANIZATION, message)

    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert await resource_row(organization_manager, message["resourceId"]) is None
    assert await outbox(outbox_reader, message["resourceId"]) == []
    recorded = await fetch_one(
        organization_manager,
        "SELECT operation_status, operation_status_reason, desired_generation"
        " FROM ipm.organization_operation WHERE operation_id = %s",
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
    assert (await handler.handle(ssot(organization_manager), ORGANIZATION, first)).kind is (
        OutcomeKind.ACCEPTED
    )
    outcome = await handler.handle(ssot(organization_manager), ORGANIZATION, second)
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)


async def test_owner_quota_blocks_the_second_organization_of_the_same_owner(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    owner = "quota-" + unique_suffix()
    first = await handler.handle(
        ssot(organization_manager), ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
    )
    blocked = await handler.handle(
        ssot(organization_manager), ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
    )
    other_owner = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        create_message(cleanup, owner="quota-" + unique_suffix(), quota=1),
    )
    unlimited = await handler.handle(
        ssot(organization_manager), ORGANIZATION, create_message(cleanup, owner=owner)
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
            ssot(organization_manager), ORGANIZATION, create_message(cleanup, owner=owner, quota=1)
        ),
        handler.handle(
            ssot(organization_manager_2),
            ORGANIZATION,
            create_message(cleanup, owner=owner, quota=1),
        ),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]

    name = "race-name-" + unique_suffix()
    results = await asyncio.gather(
        handler.handle(
            ssot(organization_manager),
            ORGANIZATION,
            create_message(cleanup, owner="a-" + owner, name=name),
        ),
        handler.handle(
            ssot(organization_manager_2),
            ORGANIZATION,
            create_message(cleanup, owner="b-" + owner, name=name),
        ),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]


async def test_update_bumps_generation_and_version_and_publishes(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    new_name = "renamed-" + unique_suffix()
    outcome = await handler.handle(
        ssot(organization_manager),
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
    messages = await outbox(outbox_reader, create["resourceId"])
    assert [item["payload"]["desiredGeneration"] for item in messages] == [1, 2]


async def test_stale_resource_version_is_a_conflict(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    outcome = await handler.handle(
        ssot(organization_manager),
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
    assert len(await outbox(outbox_reader, create["resourceId"])) == 1


async def test_unknown_resource_is_not_found(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    ghost = create_message(cleanup, owner="user-1")
    outcome = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(cleanup, create=ghost, operation="delete", version="1"),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.NOT_FOUND)


async def test_update_without_effective_change_keeps_the_generation(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    """Sem geração nova, a Operation acompanha a vigente, ainda não observada (decisão 0072)."""
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    outcome = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="1",
            specification={"name": create["data"]["specification"]["name"]},
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 1


async def test_reconciliation_change_alone_keeps_generation(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    outcome = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(
            cleanup, create=create, operation="update", version="1", reconciliation="suspended"
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED  # a geração 1 ainda não foi observada
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["reconciliation"]) == (
        2,
        1,
        "suspended",
    )
    messages = await outbox(outbox_reader, create["resourceId"])
    assert [item["payload"]["data"]["reconciliation"] for item in messages] == [
        "active",
        "suspended",
    ]


async def unprotect(
    cleanup: Cleanup, connection: Connection, create: dict[str, Any], version: str
) -> None:
    outcome = await handler.handle(
        ssot(connection),
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version=version,
            specification={"deletionProtection": False},
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED


async def test_delete_of_a_protected_organization_is_rejected(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    outcome = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(cleanup, create=create, operation="delete", version="1"),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.PROTECTED)
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["lifecycle"], row["desired_generation"]) == ("present", 1)


async def test_protection_only_update_goes_through_the_loop(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    """Campo da plataforma segue o mesmo fluxo de qualquer alteração (decisão 0072)."""
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    await unprotect(cleanup, organization_manager, create, "1")
    after = await resource_row(organization_manager, create["resourceId"])
    assert after is not None
    assert after["desired"]["deletionProtection"] is False
    assert (after["resource_version"], after["desired_generation"], after["phase"]) == (
        2,
        2,
        "Reconciling",
    )


async def test_delete_declares_absence_and_is_idempotent(
    cleanup: Cleanup, organization_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(organization_manager), ORGANIZATION, create)
    await unprotect(cleanup, organization_manager, create, "1")
    deleted = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(cleanup, create=create, operation="delete", version="2"),
    )
    assert deleted.kind is OutcomeKind.ACCEPTED
    row = await resource_row(organization_manager, create["resourceId"])
    assert row is not None
    assert (row["lifecycle"], row["phase"], row["desired_generation"]) == ("absent", "Deleting", 3)

    repeated = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(cleanup, create=create, operation="delete", version="3"),
    )
    assert repeated.kind is OutcomeKind.ACCEPTED  # sem geração nova; a 3 ainda não foi observada
    after = await handler.handle(
        ssot(organization_manager),
        ORGANIZATION,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="3",
            specification={"name": "z-" + unique_suffix()},
        ),
    )
    assert (after.kind, after.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 3


async def test_invalid_message_is_a_permanent_error(
    cleanup: Cleanup, organization_manager: Connection
) -> None:
    broken = create_message(cleanup, owner="user-1")
    broken["data"]["specification"]["name"] = "Nome Inválido!"
    with pytest.raises(PermanentMessageError, match="requested/create"):
        await handler.handle(ssot(organization_manager), ORGANIZATION, broken)

    wrong_emitter = create_message(cleanup, owner="user-1")
    wrong_emitter["emitter"] = "manager"
    with pytest.raises(PermanentMessageError, match="não é um requested de receiver deste tipo"):
        await handler.handle(ssot(organization_manager), ORGANIZATION, wrong_emitter)
