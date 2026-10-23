"""Manager: `requested` de Billing Account contra o SSOT real (docs/SSOT.md §10.1)."""

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

from bsm_account.common.contracts import generated
from bsm_account.manager.domain.errors import PermanentMessageError
from bsm_account.manager.domain.kind import ACCOUNT
from bsm_account.manager.domain.outcome import OutcomeKind, RejectionReason
from bsm_account.manager.handlers.requested import RequestedHandler

handler = RequestedHandler()
Connection = psycopg.AsyncConnection[Any]


def create_message(
    cleanup: Cleanup,
    *,
    owner: str,
    display_name: str | None = None,
    operation_id: str | None = None,
    resource_id: str | None = None,
    digest: str = DEFAULT_DIGEST,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "operationId": operation_id or str(uuid.uuid7()),
        "requestDigest": digest,
        "specification": {
            "displayName": display_name or f"Account {unique_suffix()}",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.com.br"],
        },
    }
    return requested_message(
        resource_type="account",
        resource_id=cleanup.track(resource_id or str(uuid.uuid7())),
        operation="create",
        requested_by=owner,
        data=data,
    )


def change_message(
    cleanup: Cleanup, *, create: dict[str, Any], operation: str, version: str, **data: Any
) -> dict[str, Any]:
    return requested_message(
        resource_type="account",
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
        " failure_count FROM bsm.account WHERE resource_id = %s",
        resource_id,
    )


async def outbox(outbox_reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        outbox_reader,
        "SELECT subject, payload FROM bsm.account_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_create_is_accepted_and_publishes_desired(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup, owner="user-1", display_name="Acme " + unique_suffix())
    outcome = await handler.handle(ssot(account_manager), ACCOUNT, message)

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(account_manager, message["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["phase"]) == (1, 1, "Pending")
    assert row["lifecycle"] == "present"
    assert row["reconciliation"] == "active"
    assert row["desired"] == {
        "lifecycle": "present",
        "displayName": message["data"]["specification"]["displayName"],
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.com.br"],
        "ownerAccountId": "user-1",
        "deletionProtection": True,
    }

    operations = await fetch_all(
        account_manager,
        "SELECT operation_status, operation_type, desired_generation, requested_by, request_digest"
        " FROM bsm.account_operation WHERE operation_id = %s",
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
        f"manager.desired.bsm.account.{message['resourceId']}.changed"
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
        "displayName": message["data"]["specification"]["displayName"],
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.com.br"],
        "ownerAccountId": "user-1",
        "deletionProtection": True,
    }


async def test_redelivery_is_ignored_without_new_writes(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup, owner="user-1")
    assert (await handler.handle(ssot(account_manager), ACCOUNT, message)).kind is (
        OutcomeKind.ACCEPTED
    )
    second = await handler.handle(ssot(account_manager), ACCOUNT, message)

    assert second.kind is OutcomeKind.DUPLICATE
    assert not second.digest_mismatch
    assert len(await outbox(outbox_reader, message["resourceId"])) == 1


async def test_same_operation_with_other_digest_is_flagged_and_original_prevails(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    first = create_message(cleanup, owner="user-1", digest="a" * 64)
    other = create_message(
        cleanup,
        owner="user-1",
        operation_id=first["data"]["operationId"],
        digest="b" * 64,
    )
    await handler.handle(ssot(account_manager), ACCOUNT, first)
    outcome = await handler.handle(ssot(account_manager), ACCOUNT, other)

    assert outcome.kind is OutcomeKind.DUPLICATE
    assert outcome.digest_mismatch
    assert await resource_row(account_manager, other["resourceId"]) is None


async def test_duplicate_display_name_for_same_owner_is_rejected_and_allowed_for_other_owner(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    display_name = "Dup " + unique_suffix()
    first = create_message(cleanup, owner="user-1", display_name=display_name)
    same_owner = create_message(cleanup, owner="user-1", display_name=display_name)
    other_owner = create_message(cleanup, owner="user-2", display_name=display_name)
    assert (await handler.handle(ssot(account_manager), ACCOUNT, first)).kind is (
        OutcomeKind.ACCEPTED
    )
    rejected = await handler.handle(ssot(account_manager), ACCOUNT, same_owner)
    assert (rejected.kind, rejected.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)

    accepted_other = await handler.handle(ssot(account_manager), ACCOUNT, other_owner)
    assert accepted_other.kind is OutcomeKind.ACCEPTED


async def test_concurrent_creates_respect_display_name_uniqueness_per_owner(
    cleanup: Cleanup, account_manager: Connection, account_manager_2: Connection
) -> None:
    owner = "race-" + unique_suffix()
    display_name = "Race " + unique_suffix()
    results = await asyncio.gather(
        handler.handle(
            ssot(account_manager),
            ACCOUNT,
            create_message(cleanup, owner=owner, display_name=display_name),
        ),
        handler.handle(
            ssot(account_manager_2),
            ACCOUNT,
            create_message(cleanup, owner=owner, display_name=display_name),
        ),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]


async def test_update_bumps_generation_and_version_and_publishes(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    new_name = "Renamed " + unique_suffix()
    outcome = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="1",
            specification={"displayName": new_name},
        ),
    )

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(account_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["phase"]) == (
        2,
        2,
        "Reconciling",
    )
    assert row["desired"]["displayName"] == new_name
    messages = await outbox(outbox_reader, create["resourceId"])
    assert [item["payload"]["desiredGeneration"] for item in messages] == [1, 2]


async def test_stale_resource_version_is_a_conflict(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    outcome = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="7",
            specification={"displayName": "x-" + unique_suffix()},
        ),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.CONFLICT)
    row = await resource_row(account_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 1


async def test_unknown_resource_is_not_found(cleanup: Cleanup, account_manager: Connection) -> None:
    ghost = create_message(cleanup, owner="user-1")
    outcome = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(cleanup, create=ghost, operation="delete", version="1"),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.NOT_FOUND)


async def test_update_without_effective_change_keeps_the_generation(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    """Sem geração nova, a Operation acompanha a vigente, ainda não observada (decisão 0072)."""
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    outcome = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="1",
            specification={"displayName": create["data"]["specification"]["displayName"]},
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(account_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 1


async def test_reconciliation_change_alone_keeps_generation(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    outcome = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(
            cleanup, create=create, operation="update", version="1", reconciliation="suspended"
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(account_manager, create["resourceId"])
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
        ACCOUNT,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version=version,
            specification={"deletionProtection": False},
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED


async def test_delete_of_a_protected_account_is_rejected(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    outcome = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(cleanup, create=create, operation="delete", version="1"),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.PROTECTED)
    row = await resource_row(account_manager, create["resourceId"])
    assert row is not None
    assert (row["lifecycle"], row["desired_generation"]) == ("present", 1)


async def test_protection_only_update_goes_through_the_loop(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    """Campo da plataforma segue o mesmo fluxo de qualquer alteração (decisão 0072)."""
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    await unprotect(cleanup, account_manager, create, "1")
    after = await resource_row(account_manager, create["resourceId"])
    assert after is not None
    assert after["desired"]["deletionProtection"] is False
    assert (after["resource_version"], after["desired_generation"], after["phase"]) == (
        2,
        2,
        "Reconciling",
    )


async def test_delete_declares_absence_and_is_idempotent(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup, owner="user-1")
    await handler.handle(ssot(account_manager), ACCOUNT, create)
    await unprotect(cleanup, account_manager, create, "1")
    deleted = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(cleanup, create=create, operation="delete", version="2"),
    )
    assert deleted.kind is OutcomeKind.ACCEPTED
    row = await resource_row(account_manager, create["resourceId"])
    assert row is not None
    assert (row["lifecycle"], row["phase"], row["desired_generation"]) == ("absent", "Deleting", 3)

    repeated = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(cleanup, create=create, operation="delete", version="3"),
    )
    assert repeated.kind is OutcomeKind.ACCEPTED
    after = await handler.handle(
        ssot(account_manager),
        ACCOUNT,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="3",
            specification={"displayName": "z-" + unique_suffix()},
        ),
    )
    assert (after.kind, after.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 3


async def test_invalid_message_is_a_permanent_error(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    broken = create_message(cleanup, owner="user-1")
    broken["data"]["specification"]["billingCurrency"] = "JPY"
    with pytest.raises(PermanentMessageError, match="requested/create"):
        await handler.handle(ssot(account_manager), ACCOUNT, broken)

    wrong_emitter = create_message(cleanup, owner="user-1")
    wrong_emitter["emitter"] = "manager"
    with pytest.raises(PermanentMessageError, match="não é um requested de receiver deste tipo"):
        await handler.handle(ssot(account_manager), ACCOUNT, wrong_emitter)
