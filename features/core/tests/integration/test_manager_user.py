"""Manager: `requested` de User contra o SSOT real (decisão 0014)."""

import json
import uuid
from typing import Any

import psycopg
import pytest
from support import DEFAULT_DIGEST, Cleanup, fetch_all, fetch_one, requested_message, unique_suffix

from core.manager.errors import PermanentMessageError
from core.manager.kinds import USER
from core.manager.outcome import OutcomeKind, RejectionReason
from core.manager.requested import RequestedHandler

handler = RequestedHandler()
Connection = psycopg.AsyncConnection[Any]


def register_message(cleanup: Cleanup, *, email: str | None = None) -> dict[str, Any]:
    """Um auto-cadastro: escrita anônima (docs/RESOURCE-CONTROL-LOOP.md §6.1.2)."""
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
                "email": email or f"ana.{unique_suffix()}@example.com",
            },
        },
    )


def delete_message(register: dict[str, Any], *, version: str) -> dict[str, Any]:
    return requested_message(
        resource_type="user",
        resource_id=register["resourceId"],
        operation="delete",
        requested_by=register["resourceId"],
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "resourceVersion": version,
        },
    )


async def user_row(connection: Connection, resource_id: str) -> dict[str, Any] | None:
    return await fetch_one(
        connection,
        "SELECT resource_version, desired_generation, lifecycle, desired, phase"
        ' FROM core."user" WHERE resource_id = %s',
        resource_id,
    )


async def outbox(relay: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        relay,
        "SELECT subject, payload FROM core.user_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_anonymous_registration_creates_the_user_with_normalized_email(
    cleanup: Cleanup, user_manager: Connection, relay: Connection
) -> None:
    message = register_message(cleanup, email=f"  Ana.{unique_suffix()}@Example.COM ")
    outcome = await handler.handle(user_manager, USER, message)

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await user_row(user_manager, message["resourceId"])
    assert row is not None
    expected_email = message["data"]["specification"]["email"].strip().lower()
    assert row["desired"] == {
        "lifecycle": "present",
        "platformAccess": "granted",
        "givenName": "Ana",
        "familyName": "Souza",
        "email": expected_email,
    }
    operation = await fetch_one(
        user_manager,
        "SELECT requested_by, operation_status FROM core.user_operation WHERE operation_id = %s",
        message["data"]["operationId"],
    )
    assert operation == {"requested_by": "anonymous", "operation_status": "accepted"}
    published = await outbox(relay, message["resourceId"])
    assert published[0]["subject"] == f"manager.desired.core.user.{message['resourceId']}.changed"
    assert published[0]["payload"]["data"]["email"] == expected_email


async def test_duplicate_email_is_rejected_regardless_of_case(
    cleanup: Cleanup, user_manager: Connection
) -> None:
    email = f"dup.{unique_suffix()}@example.com"
    first = register_message(cleanup, email=email)
    second = register_message(cleanup, email=email.upper())
    assert (await handler.handle(user_manager, USER, first)).kind is OutcomeKind.ACCEPTED
    outcome = await handler.handle(user_manager, USER, second)
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert await user_row(user_manager, second["resourceId"]) is None


async def test_delete_removes_personal_data_from_the_ssot_and_from_the_desired_message(
    cleanup: Cleanup, user_manager: Connection, relay: Connection
) -> None:
    message = register_message(cleanup)
    await handler.handle(user_manager, USER, message)
    outcome = await handler.handle(user_manager, USER, delete_message(message, version="1"))

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await user_row(user_manager, message["resourceId"])
    assert row is not None
    assert row["desired"] == {"lifecycle": "absent", "platformAccess": "granted"}
    assert (row["lifecycle"], row["phase"], row["desired_generation"]) == ("absent", "Deleting", 2)

    latest = (await outbox(relay, message["resourceId"]))[-1]["payload"]
    assert latest["desiredGeneration"] == 2
    assert latest["data"] == {
        "lifecycle": "absent",
        "reconciliation": "active",
        "platformAccess": "granted",
    }
    personal = message["data"]["specification"]["email"]
    assert personal not in json.dumps(latest)


async def test_update_is_not_supported_for_user(cleanup: Cleanup, user_manager: Connection) -> None:
    message = register_message(cleanup)
    await handler.handle(user_manager, USER, message)
    update = delete_message(message, version="1")
    update["operation"] = "update"
    with pytest.raises(PermanentMessageError, match="não suportada"):
        await handler.handle(user_manager, USER, update)
