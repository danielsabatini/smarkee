"""Manager: `requested` de Account contra o SSOT real (decisão 0014)."""

import json
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
    ssot,
    unique_suffix,
)

from core_account_manager.domain.account import DEFAULT_PLATFORM_ROLES
from core_account_manager.domain.errors import PermanentMessageError
from core_account_manager.domain.kind import ACCOUNT
from core_account_manager.domain.outcome import OutcomeKind, RejectionReason
from core_account_manager.handlers.requested import RequestedHandler

handler = RequestedHandler()
Connection = psycopg.AsyncConnection[Any]


def register_message(cleanup: Cleanup, *, email: str | None = None) -> dict[str, Any]:
    """Um auto-cadastro: escrita anônima (docs/RESOURCE-CONTROL-LOOP.md §6.1.2)."""
    return requested_message(
        resource_type="account",
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
        resource_type="account",
        resource_id=register["resourceId"],
        operation="delete",
        requested_by=register["resourceId"],
        data={
            "operationId": str(uuid.uuid7()),
            "requestDigest": DEFAULT_DIGEST,
            "resourceVersion": version,
        },
    )


async def account_row(connection: Connection, resource_id: str) -> dict[str, Any] | None:
    return await fetch_one(
        connection,
        "SELECT resource_version, desired_generation, lifecycle, desired, phase"
        " FROM core.account WHERE resource_id = %s",
        resource_id,
    )


async def outbox(outbox_reader: Connection, resource_id: str) -> list[dict[str, Any]]:
    return await fetch_all(
        outbox_reader,
        "SELECT subject, payload FROM core.account_outbox WHERE resource_id = %s ORDER BY sequence",
        resource_id,
    )


async def test_anonymous_registration_creates_the_account_with_normalized_email(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    message = register_message(cleanup, email=f"  Ana.{unique_suffix()}@Example.COM ")
    outcome = await handler.handle(ssot(account_manager), ACCOUNT, message)

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await account_row(account_manager, message["resourceId"])
    assert row is not None
    expected_email = message["data"]["specification"]["email"].strip().lower()
    assert row["desired"] == {
        "lifecycle": "present",
        "platformAccess": "granted",
        "platformRoles": list(DEFAULT_PLATFORM_ROLES),
        "givenName": "Ana",
        "familyName": "Souza",
        "email": expected_email,
    }
    operation = await fetch_one(
        account_manager,
        "SELECT requested_by, operation_status FROM core.account_operation WHERE operation_id = %s",
        message["data"]["operationId"],
    )
    assert operation == {"requested_by": "anonymous", "operation_status": "accepted"}
    published = await outbox(outbox_reader, message["resourceId"])
    assert (
        published[0]["subject"] == f"manager.desired.core.account.{message['resourceId']}.changed"
    )
    assert published[0]["payload"]["data"]["email"] == expected_email


async def test_duplicate_email_is_rejected_regardless_of_case(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    email = f"dup.{unique_suffix()}@example.com"
    first = register_message(cleanup, email=email)
    second = register_message(cleanup, email=email.upper())
    assert (
        await handler.handle(ssot(account_manager), ACCOUNT, first)
    ).kind is OutcomeKind.ACCEPTED
    outcome = await handler.handle(ssot(account_manager), ACCOUNT, second)
    assert (outcome.kind, outcome.reason) == (OutcomeKind.REJECTED, RejectionReason.VALIDATION)
    assert await account_row(account_manager, second["resourceId"]) is None


async def test_delete_removes_personal_data_from_the_ssot_and_from_the_desired_message(
    cleanup: Cleanup, account_manager: Connection, outbox_reader: Connection
) -> None:
    message = register_message(cleanup)
    await handler.handle(ssot(account_manager), ACCOUNT, message)
    outcome = await handler.handle(
        ssot(account_manager), ACCOUNT, delete_message(message, version="1")
    )

    assert outcome.kind is OutcomeKind.ACCEPTED
    row = await account_row(account_manager, message["resourceId"])
    assert row is not None
    assert row["desired"] == {
        "lifecycle": "absent",
        "platformAccess": "granted",
        "platformRoles": list(DEFAULT_PLATFORM_ROLES),
    }
    assert (row["lifecycle"], row["phase"], row["desired_generation"]) == ("absent", "Deleting", 2)

    latest = (await outbox(outbox_reader, message["resourceId"]))[-1]["payload"]
    assert latest["desiredGeneration"] == 2
    assert latest["data"] == {
        "lifecycle": "absent",
        "reconciliation": "active",
        "platformAccess": "granted",
        "platformRoles": list(DEFAULT_PLATFORM_ROLES),
    }
    personal = message["data"]["specification"]["email"]
    assert personal not in json.dumps(latest)


async def test_update_is_not_supported_for_account(
    cleanup: Cleanup, account_manager: Connection
) -> None:
    message = register_message(cleanup)
    await handler.handle(ssot(account_manager), ACCOUNT, message)
    update = delete_message(message, version="1")
    update["operation"] = "update"
    with pytest.raises(PermanentMessageError, match="não suportada"):
        await handler.handle(ssot(account_manager), ACCOUNT, update)
