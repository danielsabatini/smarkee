"""Leitura do `updated` de remoção da conta (decisão 0044)."""

import json
from typing import Any

import pytest

from sum_service_manager.domain.errors import PermanentMessageError
from sum_service_manager.transport.state import parse_account_removed

ACCOUNT_ID = "01a14168-b59d-7475-8db7-c5cf57fa100b"


def updated(**changes: Any) -> bytes:
    message: dict[str, Any] = {
        "messageId": "01a14168-b59d-7475-8db7-c5cf57fa1001",
        "schemaVersion": "1.0",
        "messageType": "updated",
        "emitter": "manager",
        "module": "core",
        "resourceType": "account",
        "resourceId": ACCOUNT_ID,
        "operation": "changed",
        "correlationId": "01a14168-b59d-7475-8db7-c5cf57fa1002",
        "occurredAt": "2026-10-16T10:00:00+00:00",
        "publishedAt": "2026-10-16T10:00:01+00:00",
        "data": {"phase": "Ready", "lifecycle": "absent", "resourceVersion": "9", "removed": True},
    }
    message.update(changes)
    return json.dumps(message).encode()


def test_a_removal_gives_the_account_id() -> None:
    assert parse_account_removed(updated()) == ACCOUNT_ID


def test_an_ordinary_updated_is_ignored() -> None:
    data = {"phase": "Ready", "lifecycle": "present", "resourceVersion": "3"}
    assert parse_account_removed(updated(data=data)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"module": "ipm", "resourceType": "organization"},
        {"messageType": "desired"},
        {"schemaVersion": "2.0"},
    ],
)
def test_a_message_of_another_kind_is_permanently_invalid(changes: dict[str, Any]) -> None:
    with pytest.raises(PermanentMessageError):
        parse_account_removed(updated(**changes))


def test_something_that_is_not_json_is_permanently_invalid() -> None:
    with pytest.raises(PermanentMessageError):
        parse_account_removed(b"x")
