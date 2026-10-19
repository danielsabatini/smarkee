"""O Manager aceita um `requested` com campo novo e recusa outro `MAJOR` (SCHEMA.md §13, §15)."""

from typing import Any

import pytest

from core_account.manager.domain.account import DEFAULT_PLATFORM_ROLES
from core_account.manager.domain.errors import PermanentMessageError
from core_account.manager.domain.kind import account_kind
from core_account.manager.handlers.envelope import parse_envelope

ENVELOPE: dict[str, Any] = {
    "messageId": "0199c8b2-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
    "schemaVersion": "1.0",
    "messageType": "observed",
    "emitter": "observer",
    "module": "core",
    "resourceType": "account",
    "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "operation": "changed",
    "presence": "present",
    "observedAt": "2026-10-09T14:00:00Z",
    "occurredAt": "2026-10-09T14:00:00Z",
    "publishedAt": "2026-10-09T14:00:01Z",
    "data": {},
}


def test_the_manager_accepts_a_requested_with_an_unknown_field_and_refuses_another_major() -> None:
    account = account_kind(DEFAULT_PLATFORM_ROLES)
    requested: dict[str, Any] = {
        **ENVELOPE,
        "messageType": "requested",
        "emitter": "receiver",
        "operation": "create",
        "requestedBy": "anonymous",
        "correlationId": "0199c8b0-0a1b-7c2d-8e3f-4a5b6c7d8e9f",
        "futureField": "x",
    }
    for key in ("presence", "observedAt"):
        requested.pop(key)

    parsed = parse_envelope(account, requested, message_type="requested", emitter="receiver")
    assert parsed.resource_id == ENVELOPE["resourceId"]

    with pytest.raises(PermanentMessageError):
        parse_envelope(
            account,
            {**requested, "schemaVersion": "2.0"},
            message_type="requested",
            emitter="receiver",
        )
