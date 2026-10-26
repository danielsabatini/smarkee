"""Publicação do outbox de `@@DOTTED@@` (`docs/data/POSTGRESQL.md` §11; decisão 0033).

Publica, em ordem de `sequence`, as mensagens que o Manager gravou no outbox, e só marca
`published_at` depois da confirmação do transporte (entrega pelo menos uma vez; o transporte
deduplica por `Nats-Msg-Id`). Uma única instância publica por vez, por trava consultiva de sessão:
a conexão do Publisher é dedicada e direta. Antes de cada lote a instância confirma que ainda
detém a trava. Uma mensagem fora do envelope é uma falha permanente: o lote para, ela continua
pendente (a ordem é preservada) e o Publisher sai de `ready` (decisão 0018).
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import ValidationError

from @@PACKAGE@@.common.contracts import generated
from @@PACKAGE@@.common.database import conninfo
from @@PACKAGE@@.common.ids import utc_now
from @@PACKAGE@@.common.logging_config import (
    bind_message_context,
    bind_traceparent,
)
from @@PACKAGE@@.common.ports import Publisher, PublishError
from @@PACKAGE@@.publisher.domain.publication import (
    PublicationRejectedError,
    PublicationResult,
)
from @@PACKAGE@@.publisher.settings import DatabaseSettings

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
POLL_INTERVAL_SECONDS = 0.5
LOCK_RETRY_SECONDS = 2.0
# Um lote dura uma fração da janela de deduplicação do transporte (120 s em `REQUESTED` e
# `DESIRED`), para que uma sobreposição entre instâncias seja absorvida pela deduplicação.
MAXIMUM_BATCH_SECONDS = 30.0
MAXIMUM_BACKOFF_SECONDS = 30.0

PUBLISHED_BY = "@@KEBAB@@-publisher"
"""Identidade de mensageria desta instância (`publishedBy`). O `emitter` continua `manager`."""
OUTBOX_TABLE = sql.Identifier("@@MODULE@@", "@@TYPE@@_outbox")
LOCK_KEY = "@@DOTTED@@_outbox"
"""Chave da trava consultiva de sessão: uma por tabela de outbox (`docs/data/POSTGRESQL.md`

§11.4)."""


def publication_envelope(payload: dict[str, Any], published_at: datetime) -> bytes:
    """Envelope completo da mensagem, validado de forma estrita antes de sair."""
    try:
        envelope = generated.MessageEnvelope.model_validate(
            {**payload, "publishedAt": published_at, "publishedBy": PUBLISHED_BY}
        )
    except ValidationError:
        raise PublicationRejectedError("mensagem do outbox fora do envelope") from None
    return json.dumps(envelope.model_dump(by_alias=True, mode="json", exclude_none=True)).encode()


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
            "SELECT sequence, message_id, subject, payload, traceparent FROM {table}"
            " WHERE published_at IS NULL ORDER BY sequence LIMIT %s"
        ).format(table=OUTBOX_TABLE),
        (batch_size,),
    )
    rows = await cursor.fetchall()
    started = monotonic()
    published = 0
    for row in rows:
        if monotonic() - started > maximum_seconds:
            break
        # O contexto de trace gravado pelo Manager acompanha a mensagem (decisão 0055).
        bind_traceparent(row["traceparent"])
        bind_message_context(row["payload"])
        try:
            body = publication_envelope(dict(row["payload"]), clock())
            await publisher.publish(row["subject"], body, message_id=row["message_id"])
            logger.info(
                "outbox message published",
                extra={
                    "smarkee.outbox.sequence": row["sequence"],
                    "messaging.message.id": row["message_id"],
                },
            )
        except (PublicationRejectedError, PublishError) as error:
            permanent = isinstance(error, PublicationRejectedError) or error.permanent
            logger.log(
                logging.ERROR if permanent else logging.WARNING,
                "outbox publication failed; the batch is interrupted",
                extra={
                    "smarkee.outbox.sequence": row["sequence"],
                    "messaging.message.id": row["message_id"],
                    "error.type": str(error),
                    "smarkee.failure.permanent": permanent,
                },
            )
            return PublicationResult(published=published, failed=True, permanent_failure=permanent)
        # Marca cada mensagem logo após a confirmação: uma queda no meio do lote repete o mínimo.
        await connection.execute(
            sql.SQL("UPDATE {table} SET published_at = now() WHERE sequence = %s").format(
                table=OUTBOX_TABLE
            ),
            (row["sequence"],),
        )
        published += 1
    return PublicationResult(published=published, failed=False)


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
                    exc_info=error,
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
