"""Publicação do outbox (`docs/POSTGRESQL.md` §11).

Publica, em ordem de `sequence`, as mensagens que o Manager gravou no outbox, e só marca
`published_at` depois da confirmação do transporte (entrega *pelo menos uma vez*; o transporte
deduplica por `Nats-Msg-Id`). Uma única instância publica por vez, por tabela de outbox, por
trava consultiva **de sessão**: a conexão do Publisher é dedicada e direta (sem *pooling* de
transação). Antes de cada lote a instância confirma que ainda detém a trava.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from ipm_organization_publisher.domain.publication import PublicationResult, PublishError
from ipm_organization_publisher.ids import utc_now
from ipm_organization_publisher.outbox.database import conninfo
from ipm_organization_publisher.settings import DatabaseSettings

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
POLL_INTERVAL_SECONDS = 0.5
LOCK_RETRY_SECONDS = 2.0
# Um lote dura uma fração da janela de deduplicação do transporte (120 s em `REQUESTED` e
# `DESIRED`), para que uma sobreposição entre instâncias seja absorvida pela deduplicação.
MAXIMUM_BATCH_SECONDS = 30.0
MAXIMUM_BACKOFF_SECONDS = 30.0


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Publica e aguarda a confirmação do transporte.

        `message_id` é a chave de deduplicação do transporte (`Nats-Msg-Id`).
        """
        ...


PUBLISHED_BY = "ipm-organization-publisher"
"""Identidade de mensageria desta instância (`publishedBy`): quem entregou a mensagem. O `emitter`
da mensagem continua sendo `manager`, o autor da decisão."""
OUTBOX_TABLE = sql.Identifier("ipm", "organization_outbox")
RESOURCE_TYPE = "organization"
LOCK_KEY = "ipm.organization_outbox"
"""Chave da trava consultiva de sessão: uma por tabela de outbox (`docs/POSTGRESQL.md` §11.4)."""


async def publish_pending(
    connection: psycopg.AsyncConnection[Any],
    publisher: Publisher,
    *,
    batch_size: int = BATCH_SIZE,
    maximum_seconds: float = MAXIMUM_BATCH_SECONDS,
    clock: Callable[[], datetime] = utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> PublicationResult:
    """Publica um lote, em ordem e de forma sequencial; interrompe no primeiro erro."""
    cursor = connection.cursor(row_factory=dict_row)
    await cursor.execute(
        sql.SQL(
            "SELECT sequence, message_id, subject, payload FROM {table}"
            " WHERE published_at IS NULL ORDER BY sequence LIMIT %s"
        ).format(table=OUTBOX_TABLE),
        (batch_size,),
    )
    rows = await cursor.fetchall()
    started = monotonic()
    confirmed: list[int] = []
    failed = False
    permanent = False
    for row in rows:
        if monotonic() - started > maximum_seconds:
            break
        payload: dict[str, Any] = dict(row["payload"])
        payload["publishedAt"] = clock().isoformat()
        payload["publishedBy"] = PUBLISHED_BY
        try:
            await publisher.publish(
                row["subject"], json.dumps(payload).encode(), message_id=row["message_id"]
            )
        except PublishError as error:
            logger.log(
                logging.ERROR if error.permanent else logging.WARNING,
                "outbox publication failed; the batch is interrupted",
                extra={
                    "resource_type": RESOURCE_TYPE,
                    "sequence": row["sequence"],
                    "message_id": row["message_id"],
                    "error_type": str(error),
                    "permanent": error.permanent,
                },
            )
            failed = True
            permanent = error.permanent
            break
        confirmed.append(row["sequence"])
    if confirmed:
        await connection.execute(
            sql.SQL("UPDATE {table} SET published_at = now() WHERE sequence = ANY(%s)").format(
                table=OUTBOX_TABLE
            ),
            (confirmed,),
        )
    return PublicationResult(published=len(confirmed), failed=failed, permanent_failure=permanent)


async def holds_lock(connection: psycopg.AsyncConnection[Any], lock_key: str = LOCK_KEY) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'"
        " AND pid = pg_backend_pid() AND granted AND objid = hashtext(%s)::oid)",
        (lock_key,),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def try_acquire_lock(
    connection: psycopg.AsyncConnection[Any], lock_key: str = LOCK_KEY
) -> bool:
    cursor = await connection.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (lock_key,))
    row = await cursor.fetchone()
    return bool(row and row[0])


class OutboxPublisher:
    """Mantém a instância ativa do Publisher do tipo."""

    def __init__(
        self,
        settings: DatabaseSettings,
        publisher: Publisher,
        *,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._settings = settings
        self._publisher = publisher
        self._on_cycle = on_cycle
        self.blocked_by_permanent_failure = False
        """Verdadeiro enquanto uma recusa permanente impede a publicação (readiness)."""

    async def run(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                async with await psycopg.AsyncConnection.connect(
                    conninfo(self._settings), autocommit=True
                ) as connection:
                    await self._serve(connection, stop)
                backoff = 1.0
            except (psycopg.Error, OSError) as error:
                logger.warning(
                    "publisher connection lost",
                    extra={
                        "resource_type": RESOURCE_TYPE,
                        "error_type": type(error).__name__,
                    },
                )
                await self._sleep(backoff, stop)
                backoff = min(backoff * 2, MAXIMUM_BACKOFF_SECONDS)

    async def _serve(self, connection: psycopg.AsyncConnection[Any], stop: asyncio.Event) -> None:
        while not stop.is_set() and not await try_acquire_lock(connection, LOCK_KEY):
            self._on_cycle()
            await self._sleep(LOCK_RETRY_SECONDS, stop)
        failure_backoff = 1.0
        while not stop.is_set():
            self._on_cycle()  # sinal de vida do laço (liveness)
            if not await holds_lock(connection, LOCK_KEY):
                return  # perdeu a trava: reconecta e disputa de novo
            result = await publish_pending(connection, self._publisher)
            self.blocked_by_permanent_failure = result.permanent_failure
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
