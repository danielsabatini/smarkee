"""Provisionamento automático da Billing Account Free Tier ao convergir `core.account` (0082)."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import nats.js.errors
import pytest

from bsm_account.manager.domain.account import (
    free_tier_operation_id,
    free_tier_resource_id,
)
from bsm_account.manager.domain.errors import DuplicateWriteError, PermanentMessageError
from bsm_account.manager.domain.kind import ACCOUNT
from bsm_account.manager.domain.outcome import OutcomeKind
from bsm_account.manager.domain.policy import UniqueValue
from bsm_account.manager.handlers.account_updated import AccountUpdatedHandler
from bsm_account.manager.transport.account_updated import fetch_core_account_email

ACCOUNT_ID = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def updated_envelope(**data_overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "lifecycle": "present",
        "phase": "Ready",
        "resourceVersion": "3",
        "desiredGeneration": 1,
        "observedGeneration": 1,
    }
    data.update(data_overrides)
    return {
        "messageId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d01",
        "schemaVersion": "1.0",
        "messageType": "updated",
        "emitter": "manager",
        "module": "core",
        "resourceType": "account",
        "resourceId": ACCOUNT_ID,
        "operation": "changed",
        "correlationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d02",
        "occurredAt": "2026-10-22T12:00:00+00:00",
        "publishedAt": "2026-10-22T12:00:01+00:00",
        "data": data,
    }


class FakeStore:
    def __init__(self) -> None:
        self.digests: dict[str, str] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.operations: dict[str, dict[str, Any]] = {}
        self.outbox: list[tuple[str, str, dict[str, Any]]] = []
        self.in_use = False
        self.raise_duplicate = False

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        if self.raise_duplicate:
            raise DuplicateWriteError
        yield

    async def recorded_digest(self, operation_id: str) -> str | None:
        return self.digests.get(operation_id)

    async def value_in_use(self, unique: UniqueValue, *, excluding_resource_id: str) -> bool:
        return self.in_use

    async def insert_resource(
        self, resource_id: str, *, schema_version: str, desired: Mapping[str, Any]
    ) -> None:
        self.resources[resource_id] = dict(desired)

    async def lock_for_request(self, resource_id: str) -> dict[str, Any] | None:
        desired = self.resources.get(resource_id)
        if desired is None:
            return None
        return {
            "desired": desired,
            "lifecycle": desired.get("lifecycle", "present"),
            "resource_version": 2,
        }

    async def change_desired(self, resource_id: str, **kwargs: Any) -> int | None:
        self.resources[resource_id] = dict(kwargs["desired"])
        return 2

    async def lock_for_observation(self, resource_id: str) -> dict[str, Any] | None:
        return None

    async def save_observation(self, *args: Any, **kwargs: Any) -> int:
        return 1

    async def record_execution_failure(self, *args: Any, **kwargs: Any) -> int:
        return 1

    async def delete_resource(self, resource_id: str) -> None:
        pass

    async def insert_operation(self, **kwargs: Any) -> None:
        self.operations[kwargs["operation_id"]] = kwargs
        self.digests[kwargs["operation_id"]] = kwargs["request_digest"]

    async def add_to_outbox(
        self, message: Mapping[str, Any], *, resource_id: str, subject: str
    ) -> None:
        self.outbox.append((resource_id, subject, dict(message)))

    async def lock_resource(self, resource_id: str) -> dict[str, Any] | None:
        return None

    async def set_current_operations(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def settle_operations(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def record_action_result(self, **kwargs: Any) -> bool:
        return True

    async def save_result(self, *args: Any, **kwargs: Any) -> int:
        return 1


async def test_provisions_free_tier_when_core_account_reaches_ready() -> None:
    store = FakeStore()

    async def email_of(account_id: str) -> str | None:
        assert account_id == ACCOUNT_ID
        return "ana@example.com"

    handler = AccountUpdatedHandler(
        email_of, clock=lambda: NOW, identifiers=lambda: "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99"
    )
    outcome = await handler.handle(store, ACCOUNT, updated_envelope())
    assert outcome.kind is OutcomeKind.ACCEPTED

    rid = free_tier_resource_id(ACCOUNT_ID)
    op_id = free_tier_operation_id(ACCOUNT_ID)
    assert store.resources[rid] == {
        "lifecycle": "present",
        "displayName": "Free Tier",
        "billingCurrency": "BRL",
        "billingContacts": ["ana@example.com"],
        "deletionProtection": True,
        "ownerAccountId": ACCOUNT_ID,
    }
    assert store.operations[op_id]["status"] == "accepted"
    assert len(store.outbox) == 1
    assert store.outbox[0][1] == f"manager.desired.bsm.account.{rid}.changed"


async def test_duplicate_or_existing_free_tier_is_idempotent() -> None:
    store = FakeStore()

    async def email_of(_: str) -> str | None:
        return "ana@example.com"

    handler = AccountUpdatedHandler(
        email_of, clock=lambda: NOW, identifiers=lambda: "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99"
    )
    await handler.handle(store, ACCOUNT, updated_envelope())
    second = await handler.handle(store, ACCOUNT, updated_envelope())
    assert second.kind is OutcomeKind.DUPLICATE
    assert len(store.outbox) == 1


async def test_non_ready_or_removed_or_missing_email_is_ignored() -> None:
    store = FakeStore()

    async def no_email(_: str) -> str | None:
        return None

    handler = AccountUpdatedHandler(no_email, clock=lambda: NOW)
    assert (
        await handler.handle(store, ACCOUNT, updated_envelope(phase="Pending"))
    ).kind is OutcomeKind.IGNORED
    assert (
        await handler.handle(store, ACCOUNT, updated_envelope(removed=True, lifecycle="absent"))
    ).kind is OutcomeKind.IGNORED
    assert (await handler.handle(store, ACCOUNT, updated_envelope())).kind is OutcomeKind.IGNORED
    assert store.resources == {}


async def test_core_account_removal_schedules_free_tier_removal() -> None:
    store = FakeStore()

    async def email_of(_: str) -> str | None:
        return "ana@example.com"

    handler = AccountUpdatedHandler(
        email_of, clock=lambda: NOW, identifiers=lambda: "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99"
    )
    await handler.handle(store, ACCOUNT, updated_envelope())
    rid = free_tier_resource_id(ACCOUNT_ID)
    assert store.resources[rid]["lifecycle"] == "present"

    removed = await handler.handle(
        store, ACCOUNT, updated_envelope(removed=True, lifecycle="absent")
    )
    assert removed.kind is OutcomeKind.ACCEPTED
    assert store.resources[rid]["lifecycle"] == "absent"
    assert store.resources[rid]["deletionProtection"] is False


async def test_invalid_envelope_raises_permanent_error() -> None:
    store = FakeStore()

    async def email_of(_: str) -> str | None:
        return "ana@example.com"

    handler = AccountUpdatedHandler(email_of)
    with pytest.raises(PermanentMessageError):
        await handler.handle(store, ACCOUNT, {**updated_envelope(), "module": "ipm"})


async def test_fetch_core_account_email_reads_desired_stream() -> None:
    js = MagicMock()
    raw = MagicMock()
    raw.data = b'{"data": {"email": "ana@example.com"}}'
    js.get_last_msg = AsyncMock(return_value=raw)
    assert await fetch_core_account_email(js, ACCOUNT_ID) == "ana@example.com"

    js.get_last_msg = AsyncMock(side_effect=nats.js.errors.NotFoundError)
    assert await fetch_core_account_email(js, ACCOUNT_ID) is None
