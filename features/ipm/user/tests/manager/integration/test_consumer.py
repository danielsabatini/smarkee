"""Decisão sobre a mensagem no transporte: ACK, TERM ou RETRY (docs/NATS.md §7.3 e §11)."""

import json
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any

import psycopg
import psycopg_pool
import pytest
import pytest_asyncio
from support_manager import (
    DEFAULT_DIGEST,
    Cleanup,
    dsn,
    requested_message,
    unique_suffix,
)

from ipm_user.manager.domain.errors import PermanentMessageError
from ipm_user.manager.domain.kind import USER, ResourceKind
from ipm_user.manager.domain.outcome import Outcome, OutcomeKind
from ipm_user.manager.handlers.ports import Store
from ipm_user.manager.handlers.requested import RequestedHandler
from ipm_user.manager.transport import consumers as manager_consumers
from ipm_user.manager.transport.consumers import Disposition, apply_message


@pytest_asyncio.fixture
async def pool(database_available: None) -> AsyncIterator[psycopg_pool.AsyncConnectionPool[Any]]:
    connection_pool: psycopg_pool.AsyncConnectionPool[Any] = psycopg_pool.AsyncConnectionPool(
        dsn("ipm_user_manager_login"),
        min_size=1,
        max_size=2,
        kwargs={"autocommit": True},
        open=False,
    )
    await connection_pool.open(wait=True, timeout=5)
    yield connection_pool
    await connection_pool.close()


def valid_message(cleanup: Cleanup) -> bytes:
    return json.dumps(
        requested_message(
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
                    "email": f"cons-{unique_suffix()}@example.com",
                    "roles": [],
                },
            },
        )
    ).encode()


class FlakyHandler(RequestedHandler):
    """Falha de forma transitória algumas vezes e depois funciona (ou falha para sempre)."""

    def __init__(self, error: Exception | None, failures: int) -> None:
        super().__init__()
        self.error = error
        self.failures = failures
        self.calls = 0

    async def handle(
        self,
        store: Store,
        kind: ResourceKind,
        raw_message: Mapping[str, Any],
    ) -> Outcome:
        self.calls += 1
        if self.error is not None and self.calls <= self.failures:
            raise self.error
        return Outcome(OutcomeKind.ACCEPTED)


async def test_valid_message_is_acked_and_applied(
    cleanup: Cleanup, pool: psycopg_pool.AsyncConnectionPool[Any]
) -> None:
    disposition = await apply_message(pool, RequestedHandler(), USER, valid_message(cleanup))
    assert disposition is Disposition.ACK


@pytest.mark.parametrize("data", [b"isto nao e json", b'{"messageId": "x"}'])
async def test_invalid_messages_are_terminated(
    pool: psycopg_pool.AsyncConnectionPool[Any], data: bytes
) -> None:
    assert await apply_message(pool, RequestedHandler(), USER, data) is Disposition.TERM


async def test_permanent_error_is_terminated(pool: psycopg_pool.AsyncConnectionPool[Any]) -> None:
    handler = FlakyHandler(PermanentMessageError("campo inválido"), failures=99)
    assert await apply_message(pool, handler, USER, b"{}") is Disposition.TERM
    assert handler.calls == 1


async def test_transient_error_is_retried_in_place_then_acked(
    pool: psycopg_pool.AsyncConnectionPool[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manager_consumers, "TRANSIENT_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    handler = FlakyHandler(psycopg.errors.DeadlockDetected("deadlock"), failures=2)
    assert await apply_message(pool, handler, USER, b"{}") is Disposition.ACK
    assert handler.calls == 3


async def test_persistent_transient_error_goes_back_to_the_queue(
    pool: psycopg_pool.AsyncConnectionPool[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manager_consumers, "TRANSIENT_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    handler = FlakyHandler(psycopg.errors.LockNotAvailable("lock_timeout"), failures=99)
    assert await apply_message(pool, handler, USER, b"{}") is Disposition.RETRY
    assert handler.calls == 4
