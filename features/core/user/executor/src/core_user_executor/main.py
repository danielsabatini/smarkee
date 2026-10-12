"""Entrypoint do Executor de User (`srv-core-user-executor`, decisão 0015).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import asyncio
import logging
import signal
import sys

import httpx

from core_user_executor.engine.executor import Executor
from core_user_executor.http.health import Health, serve_health
from core_user_executor.logging_config import configure_logging
from core_user_executor.provider.zitadel import ZitadelWriter
from core_user_executor.settings import UserExecutorSettings, missing_required
from core_user_executor.transport.nats import (
    ActionConsumer,
    DirectStateReader,
    JetStreamPublisher,
    connect,
    jetstream_of,
)

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: UserExecutorSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as http:
        nats_client = await connect(settings.nats)
        jetstream = jetstream_of(nats_client)
        executor = Executor(
            ZitadelWriter(settings.zitadel, http),
            JetStreamPublisher(jetstream),
            DirectStateReader(jetstream),
            settings.zitadel,
        )
        health = Health()
        health.add_check("nats", lambda: nats_client.is_connected)
        tasks = {
            f"action-p{partition}": asyncio.create_task(
                ActionConsumer(jetstream, executor, partition=partition, on_cycle=health.beat).run(
                    stop
                )
            )
            for partition in range(settings.partition.count)
        }
        tasks |= {
            "health": asyncio.create_task(serve_health(health, settings.health.port, stop)),
        }
        health.mark_started()
        logger.info("user executor started")
        waiter = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({waiter, *tasks.values()}, return_when=asyncio.FIRST_COMPLETED)

        exit_code = 0
        for name, task in tasks.items():
            if task in done:
                exit_code = 1
                logger.error("task stopped unexpectedly", extra={"task": name})
        stop.set()
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(tasks, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "task failed", extra={"task": name, "error_type": type(result).__name__}
                )
                exit_code = 1
        waiter.cancel()
        await nats_client.drain()
    return exit_code


def main() -> None:
    configure_logging()
    settings = UserExecutorSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
