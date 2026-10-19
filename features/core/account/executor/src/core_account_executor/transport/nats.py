"""Adaptadores do NATS JetStream do Executor (`docs/NATS.md` §7.5).

- consumer **durável** de `ACTION` (um só, `max_ack_pending = 1`: uma `action` por vez no serviço,
  *single-flight*), criado pela infraestrutura;
- leitura direta (Direct Get) do último `desired` e do último resultado do recurso, sem consumer e
  sem cache, somente leitura.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from core_account_executor.engine.executor import Disposition, Executor, PublishError
from core_account_executor.logging_config import (
    TRACEPARENT_HEADER,
    bind_message_context,
    bind_traceparent,
    current_traceparent,
)
from core_account_executor.settings import NatsSettings

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_SECONDS = 5.0
ACTION_STREAM = "ACTION"
DURABLE_NAME = "core-account-executor-action"
"""Prefixo do consumer; cada partição tem o seu, `<prefixo>-p<índice>` (decisão 0018)."""
REDELIVERY_DELAY_SECONDS = 5.0


async def connect(settings: NatsSettings, *, name: str = "core-account-executor") -> NatsClient:
    password = settings.password.get_secret_value() if settings.password else None
    # `nats.connect` aceita opções livres; o pyright não as conhece.
    return await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=[settings.url], user=settings.user, password=password, name=name
    )


def jetstream_of(client: NatsClient) -> JetStreamContext:
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


class JetStreamPublisher:
    """Publica `completed` e `failed` e espera a confirmação do servidor."""

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        headers = {"Nats-Msg-Id": message_id}
        traceparent = current_traceparent()
        if traceparent is not None:
            headers[TRACEPARENT_HEADER] = traceparent
        try:
            await self._jetstream.publish(
                subject, payload, timeout=PUBLISH_TIMEOUT_SECONDS, headers=headers
            )
        except (nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError) as error:
            raise PublishError(type(error).__name__) from error


class DirectStateReader:
    """Último valor de um Subject por Direct Get (`allow_direct` em `DESIRED` e `RESULT`)."""

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def last_desired(self, resource_id: str) -> Mapping[str, Any] | None:
        return await self._last("DESIRED", f"manager.desired.core.account.{resource_id}.changed")

    async def last_result(
        self, resource_id: str, operation: str, kind: str
    ) -> Mapping[str, Any] | None:
        return await self._last("RESULT", f"executor.{kind}.core.account.{resource_id}.{operation}")

    async def _last(self, stream: str, subject: str) -> Mapping[str, Any] | None:
        try:
            raw = await self._jetstream.get_last_msg(stream, subject, direct=True)
        except nats.js.errors.NotFoundError:
            return None
        document = json.loads(raw.data or b"{}")
        return document if isinstance(document, dict) else None  # pyright: ignore[reportUnknownVariableType]


class ActionConsumer:
    """Consumer de trabalho de uma partição do Executor: ACK só depois de publicar o resultado.

    O Stream `ACTION` particiona por `resourceId` (`subject_transform`); cada partição tem um
    consumer com `max_ack_pending=1`. Assim há uma `action` por vez em cada recurso e até
    `partitions` recursos em paralelo.
    """

    def __init__(
        self,
        jetstream: JetStreamContext,
        executor: Executor,
        *,
        partition: int,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._durable = f"{DURABLE_NAME}-p{partition}"
        self._on_cycle = on_cycle
        self._jetstream = jetstream
        self._executor = executor
        self._fetch_timeout = fetch_timeout_seconds

    async def run(self, stop: asyncio.Event) -> None:
        subscription = await self._jetstream.pull_subscribe_bind(
            consumer=self._durable, stream=ACTION_STREAM
        )
        while not stop.is_set():
            self._on_cycle()  # sinal de vida do laço (liveness)
            try:
                messages = await subscription.fetch(1, timeout=self._fetch_timeout)
            except TimeoutError:
                continue
            except (nats.errors.Error, nats.js.errors.Error) as error:
                logger.warning("fetch failed", exc_info=error)
                await asyncio.sleep(1.0)
                continue
            for message in messages:
                # Contexto de trace vem no header NATS (decisão 0055) e vale só para esta mensagem.
                bind_traceparent((message.headers or {}).get(TRACEPARENT_HEADER))
                bind_message_context(message.data)
                try:
                    await self._settle(message)
                finally:
                    bind_traceparent(None)

    async def _settle(self, message: Msg) -> None:
        try:
            disposition = await self._executor.handle(message.data)
        except (PublishError, nats.errors.Error, nats.js.errors.Error, OSError) as error:
            # Falha de infraestrutura (não do provedor): a action volta à fila.
            logger.warning(
                "action handling failed; it returns to the queue",
                exc_info=error,
            )
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
            return
        if disposition is Disposition.TERM:
            await message.term()
        else:
            await message.ack()
