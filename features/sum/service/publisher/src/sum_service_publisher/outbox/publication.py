"""Publicação do outbox de `sum.service` (`docs/POSTGRESQL.md` §11; decisão 0033).

Publica, em ordem de `sequence`, as mensagens que o Manager gravou, e só marca `published_at` depois
da confirmação do transporte (entrega pelo menos uma vez; o transporte deduplica por `Nats-Msg-Id`).
Uma única instância publica por vez, por trava consultiva de sessão, numa conexão dedicada em
autocommit. Uma mensagem fora do contrato para o lote e não é marcada: o erro vai para quem opera.
"""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from psycopg import AsyncConnection
from psycopg.rows import dict_row, tuple_row
from pydantic import ValidationError

from sum_service_publisher.contracts import generated
from sum_service_publisher.ids import utc_now

PUBLISHED_BY = "sum-service-publisher"
"""Identidade de mensageria desta instância (`publishedBy`). O `emitter` continua `manager`."""
LOCK_KEY = "sum.service_outbox"
BATCH_SIZE = 100


class PublishError(Exception):
    """O transporte recusou a publicação. `permanent` é verdadeiro quando repetir não resolve."""

    def __init__(self, reason: str, *, permanent: bool) -> None:
        super().__init__(reason)
        self.permanent = permanent


class PublicationRejectedError(Exception):
    """Uma mensagem do outbox não atende ao envelope: o lote para e ela continua pendente."""


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Publica e aguarda a confirmação do transporte. `message_id` é o `Nats-Msg-Id`."""
        ...


def publication_envelope(payload: dict[str, Any], published_at: datetime) -> bytes:
    """Envelope completo da mensagem, validado de forma estrita antes de sair."""
    try:
        envelope = generated.MessageEnvelope.model_validate(
            {**payload, "publishedAt": published_at, "publishedBy": PUBLISHED_BY}
        )
    except ValidationError:
        raise PublicationRejectedError("mensagem do outbox fora do envelope") from None
    return json.dumps(envelope.model_dump(by_alias=True, mode="json")).encode()


async def publish_pending(
    connection: AsyncConnection[Any],
    publisher: Publisher,
    *,
    batch_size: int = BATCH_SIZE,
    clock: Callable[[], datetime] = utc_now,
) -> int:
    """Publica um lote de mensagens pendentes. Devolve quantas foram confirmadas (0 sem a trava)."""
    locked = await _try_lock(connection)
    if not locked:
        return 0
    try:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT sequence, message_id, subject, payload FROM sum.service_outbox "
                "WHERE published_at IS NULL ORDER BY sequence LIMIT %s",
                (batch_size,),
            )
            pending = await cursor.fetchall()
        published = 0
        for row in pending:
            body = publication_envelope(row["payload"], clock())
            await publisher.publish(row["subject"], body, message_id=row["message_id"])
            await connection.execute(
                "UPDATE sum.service_outbox SET published_at = %s WHERE sequence = %s",
                (clock(), row["sequence"]),
            )
            published += 1
        return published
    finally:
        await connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))


async def _try_lock(connection: AsyncConnection[Any]) -> bool:
    # Cursor de tupla: a trava não depende do formato de linha da conexão.
    async with connection.cursor(row_factory=tuple_row) as cursor:
        await cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        row = await cursor.fetchone()
    return bool(row is not None and row[0])
