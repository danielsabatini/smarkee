"""Manager: `requested` do usuário da Organization contra o SSOT real (docs/SSOT.md §10.1)."""

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

from ipm_user.common.contracts import generated
from ipm_user.manager.domain.errors import PermanentMessageError
from ipm_user.manager.domain.kind import USER
from ipm_user.manager.domain.outcome import OutcomeKind, RejectionReason
from ipm_user.manager.handlers.requested import RequestedHandler

handler = RequestedHandler()
Connection = psycopg.AsyncConnection[Any]


def organization_id() -> str:
    return f"org-{unique_suffix()}"


def create_message(
    cleanup: Cleanup,
    *,
    owner: str = "root-1",
    organization: str = "org-1",
    email: str | None = None,
    quota: int | None = None,
    operation_id: str | None = None,
    digest: str = DEFAULT_DIGEST,
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "operationId": operation_id or str(uuid.uuid7()),
        "requestDigest": digest,
        "specification": {
            "organizationId": organization,
            "givenName": "Bia",
            "familyName": "Lima",
            "email": email or f"u-{unique_suffix()}@example.com",
            "permissions": permissions if permissions is not None else ["ipm.user.get"],
            "deletionProtection": False,
        },
    }
    if quota is not None:
        data["organizationQuotaLimit"] = quota
    return requested_message(
        resource_type="user",
        resource_id=cleanup.track(str(uuid.uuid7())),
        operation="create",
        requested_by=owner,
        data=data,
    )


def change_message(
    cleanup: Cleanup, *, create: dict[str, Any], operation: str, version: str, **data: Any
) -> dict[str, Any]:
    return requested_message(
        resource_type="user",
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
        " failure_count FROM ipm.user WHERE resource_id = %s",
        resource_id,
    )


async def outbox(outbox_reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        outbox_reader,
        "SELECT subject, payload FROM ipm.user_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def handle(connection: Connection, message: dict[str, Any]) -> Any:
    return await handler.handle(ssot(connection), USER, message)


async def test_create_is_accepted_and_publishes_desired(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup, owner="root-1")
    outcome = await handle(user_manager, message)

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(user_manager, message["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["phase"]) == (1, 1, "Pending")
    assert (row["lifecycle"], row["reconciliation"]) == ("present", "active")
    specification = message["data"]["specification"]
    # Nasce desprotegido (decisão 0077); quem pediu não entra no `desired`.
    assert row["desired"] == {"lifecycle": "present", **specification}

    operations = await fetch_all(
        user_manager,
        "SELECT operation_status, operation_type, desired_generation, requested_by, request_digest"
        " FROM ipm.user_operation WHERE operation_id = %s",
        message["data"]["operationId"],
    )
    assert [dict(item) for item in operations] == [
        {
            "operation_status": "accepted",
            "operation_type": "create",
            "desired_generation": 1,
            "requested_by": "root-1",
            "request_digest": DEFAULT_DIGEST,
        }
    ]

    published = await outbox(outbox_reader, message["resourceId"])
    assert len(published) == 1
    assert published[0]["subject"] == f"manager.desired.ipm.user.{message['resourceId']}.changed"
    envelope = generated.MessageEnvelope.model_validate(published[0]["payload"])
    assert (envelope.message_type.value, envelope.emitter.value) == ("desired", "manager")
    assert envelope.desired_generation == 1
    assert envelope.causation_id == message["messageId"]
    assert envelope.data == {"lifecycle": "present", "reconciliation": "active", **specification}


async def test_redelivery_is_ignored_without_new_writes(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup)
    assert (await handle(user_manager, message)).kind is OutcomeKind.ACCEPTED
    second = await handle(user_manager, message)
    assert second.kind is OutcomeKind.DUPLICATE and not second.digest_mismatch
    assert len(await outbox(outbox_reader, message["resourceId"])) == 1


async def test_same_operation_with_other_digest_is_flagged_and_original_prevails(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    first = create_message(cleanup, digest="a" * 64)
    other = create_message(cleanup, operation_id=first["data"]["operationId"], digest="b" * 64)
    await handle(user_manager, first)
    outcome = await handle(user_manager, other)
    assert outcome.kind is OutcomeKind.DUPLICATE and outcome.digest_mismatch
    assert await resource_row(user_manager, other["resourceId"]) is None


async def test_a_permission_outside_the_module_is_rejected_without_changing_anything(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    message = create_message(cleanup, permissions=["core.account.get"])
    outcome = await handle(user_manager, message)

    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert await resource_row(user_manager, message["resourceId"]) is None
    assert await outbox(outbox_reader, message["resourceId"]) == []
    recorded = await fetch_one(
        user_manager,
        "SELECT operation_status, operation_status_reason, desired_generation"
        " FROM ipm.user_operation WHERE operation_id = %s",
        message["data"]["operationId"],
    )
    assert recorded == {
        "operation_status": "rejected",
        "operation_status_reason": "validation",
        "desired_generation": None,
    }


async def test_the_email_is_unique_within_the_organization_only(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    organization, email = organization_id(), f"dup-{unique_suffix()}@example.com"
    first = create_message(cleanup, organization=organization, email=email)
    second = create_message(cleanup, organization=organization, email=email)
    elsewhere = create_message(cleanup, organization=organization_id(), email=email)
    assert (await handle(user_manager, first)).kind is OutcomeKind.ACCEPTED
    outcome = await handle(user_manager, second)
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert (await handle(user_manager, elsewhere)).kind is OutcomeKind.ACCEPTED


async def test_the_quota_of_users_per_organization(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    organization = organization_id()

    async def create(quota: int | None, target: str = organization) -> OutcomeKind:
        message = create_message(cleanup, organization=target, quota=quota)
        return (await handle(user_manager, message)).kind

    assert await create(2) is OutcomeKind.ACCEPTED
    assert await create(2) is OutcomeKind.ACCEPTED
    assert await create(2) is OutcomeKind.REJECTED
    assert await create(2, organization_id()) is OutcomeKind.ACCEPTED  # outra Organization
    assert await create(None) is OutcomeKind.ACCEPTED  # sem limite (operador)


async def test_concurrent_creates_respect_quota_and_email_uniqueness(
    cleanup: Cleanup, user_manager: Connection, user_manager_2: Connection
) -> None:
    organization = organization_id()
    results = await asyncio.gather(
        handle(user_manager, create_message(cleanup, organization=organization, quota=1)),
        handle(user_manager_2, create_message(cleanup, organization=organization, quota=1)),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]

    organization, email = organization_id(), f"race-{unique_suffix()}@example.com"
    results = await asyncio.gather(
        handle(user_manager, create_message(cleanup, organization=organization, email=email)),
        handle(user_manager_2, create_message(cleanup, organization=organization, email=email)),
    )
    assert sorted(result.kind.value for result in results) == ["accepted", "rejected"]


async def test_update_of_permissions_bumps_generation_and_version_and_publishes(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup)
    await handle(user_manager, create)
    permissions = ["ipm.user.get", "ipm.user.list"]
    outcome = await handle(
        user_manager,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="1",
            specification={"permissions": permissions},
        ),
    )

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(user_manager, create["resourceId"])
    assert row is not None
    assert (row["resource_version"], row["desired_generation"], row["phase"]) == (
        2,
        2,
        "Reconciling",
    )
    assert row["desired"]["permissions"] == permissions
    messages = await outbox(outbox_reader, create["resourceId"])
    assert [item["payload"]["desiredGeneration"] for item in messages] == [1, 2]


async def test_stale_resource_version_is_a_conflict(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup)
    await handle(user_manager, create)
    outcome = await handle(
        user_manager,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="7",
            specification={"permissions": []},
        ),
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.CONFLICT)
    row = await resource_row(user_manager, create["resourceId"])
    assert row is not None and (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 1


async def test_unknown_resource_is_not_found(cleanup: Cleanup, user_manager: Connection) -> None:
    ghost = create_message(cleanup)
    outcome = await handle(
        user_manager, change_message(cleanup, create=ghost, operation="delete", version="1")
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.NOT_FOUND)


async def test_update_without_effective_change_keeps_the_generation(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    """Sem geração nova, a Operation acompanha a vigente, ainda não observada (decisão 0072)."""
    create = create_message(cleanup)
    await handle(user_manager, create)
    same = {"permissions": create["data"]["specification"]["permissions"]}
    outcome = await handle(
        user_manager,
        change_message(cleanup, create=create, operation="update", version="1", specification=same),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await resource_row(user_manager, create["resourceId"])
    assert row is not None and (row["resource_version"], row["desired_generation"]) == (1, 1)
    assert len(await outbox(outbox_reader, create["resourceId"])) == 1


async def test_reconciliation_change_alone_keeps_generation(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup)
    await handle(user_manager, create)
    outcome = await handle(
        user_manager,
        change_message(
            cleanup, create=create, operation="update", version="1", reconciliation="suspended"
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED  # a geração 1 ainda não foi observada
    row = await resource_row(user_manager, create["resourceId"])
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


async def protect(
    cleanup: Cleanup, connection: Connection, create: dict[str, Any], version: str
) -> None:
    outcome = await handle(
        connection,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version=version,
            specification={"deletionProtection": True},
        ),
    )
    assert outcome.kind is OutcomeKind.ACCEPTED


async def test_protection_only_update_goes_through_the_loop(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    """Campo da plataforma segue o mesmo fluxo de qualquer alteração (decisão 0072)."""
    create = create_message(cleanup)
    await handle(user_manager, create)
    await protect(cleanup, user_manager, create, "1")
    after = await resource_row(user_manager, create["resourceId"])
    assert after is not None
    assert after["desired"]["deletionProtection"] is True
    assert (after["resource_version"], after["desired_generation"], after["phase"]) == (
        2,
        2,
        "Reconciling",
    )


async def test_delete_of_a_protected_user_is_rejected(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    create = create_message(cleanup)
    await handle(user_manager, create)
    await protect(cleanup, user_manager, create, "1")
    outcome = await handle(
        user_manager, change_message(cleanup, create=create, operation="delete", version="2")
    )
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.PROTECTED)
    row = await resource_row(user_manager, create["resourceId"])
    assert row is not None and (row["lifecycle"], row["desired_generation"]) == ("present", 2)


async def test_delete_declares_absence_without_personal_data_and_is_idempotent(
    cleanup: Cleanup, user_manager: Connection, outbox_reader: Connection
) -> None:
    create = create_message(cleanup)
    await handle(user_manager, create)
    deleted = await handle(
        user_manager, change_message(cleanup, create=create, operation="delete", version="1")
    )
    assert deleted.kind is OutcomeKind.ACCEPTED  # desprotegido por padrão (decisão 0077)
    row = await resource_row(user_manager, create["resourceId"])
    assert row is not None
    assert (row["lifecycle"], row["phase"], row["desired_generation"]) == ("absent", "Deleting", 2)
    assert not {"givenName", "familyName", "email"} & set(row["desired"])
    assert row["desired"]["organizationId"] == "org-1"

    repeated = await handle(
        user_manager, change_message(cleanup, create=create, operation="delete", version="2")
    )
    assert repeated.kind is OutcomeKind.ACCEPTED  # sem geração nova; a 2 ainda não foi observada
    after = await handle(
        user_manager,
        change_message(
            cleanup,
            create=create,
            operation="update",
            version="2",
            specification={"permissions": []},
        ),
    )
    assert (after.kind, after.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    messages = await outbox(outbox_reader, create["resourceId"])
    assert len(messages) == 2
    assert "email" not in messages[-1]["payload"]["data"]


async def test_invalid_message_is_a_permanent_error(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    broken = create_message(cleanup)
    broken["data"]["specification"]["email"] = "não é e-mail"
    with pytest.raises(PermanentMessageError, match="requested/create"):
        await handle(user_manager, broken)

    wrong_emitter = create_message(cleanup)
    wrong_emitter["emitter"] = "manager"
    with pytest.raises(PermanentMessageError, match="não é um requested de receiver deste tipo"):
        await handle(user_manager, wrong_emitter)
