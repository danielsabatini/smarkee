"""Relay do outbox (`docs/POSTGRESQL.md` §11).

Publica, em ordem de `sequence`, as mensagens que o Manager gravou no outbox, e só marca
`published_at` depois da confirmação do transporte (entrega *pelo menos uma vez*; o transporte
deduplica por `Nats-Msg-Id`). Uma única instância publica por vez, por tabela de outbox, por
trava consultiva **de sessão**: a conexão do relay é dedicada e direta (sem *pooling* de
transação). Antes de cada lote a instância confirma que ainda detém a trava.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from core.database import conninfo
from core.ids import utc_now
from core.manager.kinds import ResourceKind
from core.messaging.publisher import Publisher, PublishError
from core.settings import DatabaseSettings

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
POLL_INTERVAL_SECONDS = 0.5
LOCK_RETRY_SECONDS = 2.0
# Um lote dura uma fração da janela de deduplicação do transporte (120 s em `REQUESTED` e
# `DESIRED`), para que uma sobreposição entre instâncias seja absorvida pela deduplicação.
MAXIMUM_BATCH_SECONDS = 30.0
MAXIMUM_BACKOFF_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class RelayResult:
    published: int
    failed: bool


def lock_key(kind: ResourceKind) -> str:
    return f"core.{kind.resource_type}_outbox"


async def publish_pending(
    connection: psycopg.AsyncConnection[Any],
    kind: ResourceKind,
    publisher: Publisher,
    *,
    batch_size: int = BATCH_SIZE,
    maximum_seconds: float = MAXIMUM_BATCH_SECONDS,
    clock: Callable[[], datetime] = utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> RelayResult:
    """Publica um lote, em ordem e de forma sequencial; interrompe no primeiro erro."""
    cursor = connection.cursor(row_factory=dict_row)
    await cursor.execute(
        sql.SQL(
            "SELECT sequence, message_id, subject, payload FROM {table}"
            " WHERE published_at IS NULL ORDER BY sequence LIMIT %s"
        ).format(table=kind.outbox_table),
        (batch_size,),
    )
    rows = await cursor.fetchall()
    started = monotonic()
    confirmed: list[int] = []
    failed = False
    for row in rows:
        if monotonic() - started > maximum_seconds:
            break
        payload: dict[str, Any] = dict(row["payload"])
        payload["publishedAt"] = clock().isoformat()
        try:
            await publisher.publish(
                row["subject"], json.dumps(payload).encode(), message_id=row["message_id"]
            )
        except PublishError as error:
            logger.warning(
                "outbox publication failed; the batch is interrupted",
                extra={"resource_type": kind.resource_type, "error_type": str(error)},
            )
            failed = True
            break
        confirmed.append(row["sequence"])
    if confirmed:
        await connection.execute(
            sql.SQL("UPDATE {table} SET published_at = now() WHERE sequence = ANY(%s)").format(
                table=kind.outbox_table
            ),
            (confirmed,),
        )
    return RelayResult(published=len(confirmed), failed=failed)


async def holds_lock(connection: psycopg.AsyncConnection[Any], kind: ResourceKind) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'"
        " AND pid = pg_backend_pid() AND granted AND objid = hashtext(%s)::oid)",
        (lock_key(kind),),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def try_acquire_lock(connection: psycopg.AsyncConnection[Any], kind: ResourceKind) -> bool:
    cursor = await connection.execute(
        "SELECT pg_try_advisory_lock(hashtext(%s))", (lock_key(kind),)
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


class OutboxRelay:
    """Mantém a instância ativa do relay de um tipo de recurso."""

    def __init__(
        self, settings: DatabaseSettings, kind: ResourceKind, publisher: Publisher
    ) -> None:
        self._settings = settings
        self._kind = kind
        self._publisher = publisher

    async def run(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                async with await psycopg.AsyncConnection.connect(
                    conninfo(self._settings, "relay"), autocommit=True
                ) as connection:
                    await self._serve(connection, stop)
                backoff = 1.0
            except (psycopg.Error, OSError) as error:
                logger.warning(
                    "relay connection lost",
                    extra={
                        "resource_type": self._kind.resource_type,
                        "error_type": type(error).__name__,
                    },
                )
                await self._sleep(backoff, stop)
                backoff = min(backoff * 2, MAXIMUM_BACKOFF_SECONDS)

    async def _serve(self, connection: psycopg.AsyncConnection[Any], stop: asyncio.Event) -> None:
        while not stop.is_set() and not await try_acquire_lock(connection, self._kind):
            await self._sleep(LOCK_RETRY_SECONDS, stop)
        failure_backoff = 1.0
        while not stop.is_set():
            if not await holds_lock(connection, self._kind):
                return  # perdeu a trava: reconecta e disputa de novo
            result = await publish_pending(connection, self._kind, self._publisher)
            if result.failed:
                await self._sleep(failure_backoff, stop)
                failure_backoff = min(failure_backoff * 2, MAXIMUM_BACKOFF_SECONDS)
            else:
                failure_backoff = 1.0
                if result.published == 0:
                    await self._sleep(POLL_INTERVAL_SECONDS, stop)

    @staticmethod
    async def _sleep(seconds: float, stop: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            return
