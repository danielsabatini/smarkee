"""Laço de consumo pull de um consumer durável (`docs/messaging/NATS.md` §7.3).

A mensagem é confirmada (ACK) depois que o motor a processa. Se o motor falhar, a mensagem volta
à fila com atraso (`nak`). Os consumers são declarados pela infraestrutura (`sum-service-consumer`).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from nats.aio.msg import Msg
from nats.js import JetStreamContext

from sum_service.common.messaging import REDELIVERY_DELAY_SECONDS, consume

logger = logging.getLogger(__name__)


class PullConsumer:
    def __init__(
        self,
        jetstream: JetStreamContext,
        *,
        stream: str,
        durable: str,
        handle: Callable[[bytes], Awaitable[object]],
        batch_size: int = 10,
        fetch_timeout_seconds: float = 2.0,
        on_cycle: Callable[[], None] = lambda: None,
    ) -> None:
        self._jetstream = jetstream
        self._stream = stream
        self._durable = durable
        self._handle = handle
        self._batch_size = batch_size
        self._fetch_timeout = fetch_timeout_seconds
        self._on_cycle = on_cycle

    async def run(self, stop: asyncio.Event) -> None:
        subscription = await self._jetstream.pull_subscribe_bind(
            consumer=self._durable, stream=self._stream
        )
        await consume(
            subscription,
            self._settle,
            stop,
            batch_size=self._batch_size,
            fetch_timeout_seconds=self._fetch_timeout,
            on_cycle=self._on_cycle,
        )

    async def _settle(self, message: Msg) -> None:
        try:
            await self._handle(message.data)
        except Exception as error:  # um erro de processamento volta à fila; nunca derruba o laço
            logger.error(
                "message processing failed; it will be redelivered",
                extra={"messaging.consumer.group.name": self._durable},
                exc_info=error,
            )
            await message.nak(delay=REDELIVERY_DELAY_SECONDS)
            return
        await message.ack()
        logger.debug(
            "message handled",
            extra={
                "messaging.consumer.group.name": self._durable,
                "smarkee.outcome": "acknowledged",
            },
        )
