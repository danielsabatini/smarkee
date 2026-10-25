"""Adaptadores do NATS JetStream do Executor (`docs/NATS.md` §7.5).

- consumer **durável** de `ACTION` (um só por partição, `max_ack_pending = 1`: uma `action` por vez
  no recurso, *single-flight*), criado pela infraestrutura;
- leitura direta (Direct Get) do último `desired` e do último resultado do recurso, sem consumer e
  sem cache, somente leitura.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

import nats.errors
import nats.js.errors
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from ipm_permission.common.messaging import consume
from ipm_permission.common.ports import PublishError
from ipm_permission.executor.engine.executor import Disposition, Executor

logger = logging.getLogger(__name__)

ACTION_STREAM = "ACTION"
DURABLE_NAME = "ipm-permission-executor-action"
"""Prefixo do consumer; cada partição tem o seu, `<prefixo>-p<índice>` (decisão 0018)."""
REDELIVERY_DELAY_SECONDS = 5.0


class DirectStateReader:
    """Último valor de um Subject por Direct Get (`allow_direct` em `DESIRED` e `RESULT`)."""

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def last_desired(self, resource_id: str) -> Mapping[str, Any] | None:
        return await self._last("DESIRED", f"manager.desired.ipm.permission.{resource_id}.changed")

    async def last_result(
        self, resource_id: str, operation: str, kind: str
    ) -> Mapping[str, Any] | None:
        return await self._last(
            "RESULT", f"executor.{kind}.ipm.permission.{resource_id}.{operation}"
        )

    async def _last(self, stream: str, subject: str) -> Mapping[str, Any] | None:
        try:
            raw = await self._jetstream.get_last_msg(stream, subject, direct=True)
        except nats.js.errors.NotFoundError:
            return None
        document = json.loads(raw.data or b"{}")
        return document if isinstance(document, dict) else None  # pyright: ignore[reportUnknownVariableType]


class ActionConsumer:
    """Consumer de trabalho de uma partição do Executor: ACK só depois de publicar o resultado."""

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
        await consume(
            subscription,
            self._settle,
            stop,
            batch_size=1,
            fetch_timeout_seconds=self._fetch_timeout,
            on_cycle=self._on_cycle,
        )

    async def _settle(self, message: Msg) -> None:
        try:
            disposition = await self._executor.handle(message.data)
        except (PublishError, nats.errors.Error, nats.js.errors.Error, OSError) as error:
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
