"""Consumer de `manager.updated.core.account.>` para o Manager de `bsm.account` (decisão 0082)."""

import json
import logging
from collections.abc import Callable
from typing import Any, cast

import nats.js.errors
import psycopg_pool
from nats.js import JetStreamContext

from bsm_account.manager.domain.kind import ResourceKind
from bsm_account.manager.handlers.account_updated import AccountUpdatedHandler
from bsm_account.manager.transport.consumers import StreamConsumer

logger = logging.getLogger(__name__)

UPDATED_STREAM = "UPDATED"
DESIRED_STREAM = "DESIRED"
CORE_ACCOUNT_DESIRED_SUBJECT = "manager.desired.core.account.{account_id}.changed"


async def fetch_core_account_email(jetstream: JetStreamContext, account_id: str) -> str | None:
    """Lê o `email` da última mensagem `desired` de `core.account` no Stream `DESIRED`."""
    subject = CORE_ACCOUNT_DESIRED_SUBJECT.format(account_id=account_id)
    try:
        raw = await jetstream.get_last_msg(DESIRED_STREAM, subject)
    except nats.js.errors.NotFoundError:
        return None
    try:
        document = cast("object", json.loads(raw.data or b"{}"))
    except ValueError:
        return None
    if not isinstance(document, dict):
        return None
    data = cast("dict[str, Any]", document).get("data")
    if not isinstance(data, dict):
        return None
    email = cast("dict[str, Any]", data).get("email")
    return email if isinstance(email, str) and email else None


class AccountUpdatedConsumer(StreamConsumer):
    """Consumer durável de `manager.updated.core.account.>` para provisionar a conta Free Tier."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        pool: psycopg_pool.AsyncConnectionPool[Any],
        kind: ResourceKind,
        *,
        handler: AccountUpdatedHandler | None = None,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(
            jetstream,
            pool,
            kind,
            handler
            or AccountUpdatedHandler(
                lambda account_id: fetch_core_account_email(jetstream, account_id)
            ),
            stream=UPDATED_STREAM,
            name_suffix="account-updated",
            fetch_timeout_seconds=fetch_timeout_seconds,
            on_cycle=on_cycle,
        )
