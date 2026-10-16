"""Entrypoint do Observer de Account (`core-account-observer`, decisão 0015).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a observação periódica. O Observer não acessa o SSOT e só lê o Zitadel.
"""

import asyncio
import logging
import signal
import sys

import httpx

from core_account_observer.engine.observer import Observer, periodic_observation
from core_account_observer.http.health import Health, serve_health
from core_account_observer.logging_config import configure_logging
from core_account_observer.provider.zitadel import ZitadelReader
from core_account_observer.settings import AccountObserverSettings, missing_required
from core_account_observer.transport.nats import (
    STREAMS,
    JetStreamPublisher,
    StateConsumer,
    connect,
    jetstream_of,
    new_instance_name,
)

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: AccountObserverSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as http:
        nats_client = await connect(settings.nats)
        health = Health()
        health.add_check("nats", lambda: nats_client.is_connected)
        jetstream = jetstream_of(nats_client)
        observer = Observer(
            ZitadelReader(settings.zitadel, http), JetStreamPublisher(jetstream), settings
        )
        instance = new_instance_name()
        tasks = {
            suffix: asyncio.create_task(
                StateConsumer(
                    jetstream,
                    observer,
                    stream=stream,
                    filter_subject=subject,
                    name_suffix=suffix,
                    instance=instance,
                    inactive_threshold_seconds=settings.nats.consumer_inactive_threshold_seconds,
                    on_cycle=health.beat,
                ).run(stop)
            )
            for stream, subject, suffix in STREAMS
        }
        tasks["periodic"] = asyncio.create_task(
            periodic_observation(observer, settings, stop, on_cycle=health.beat)
        )
        tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
        health.mark_started()
        logger.info(
            "account observer started",
            extra={
                "instance": instance,
                "partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
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
    settings = AccountObserverSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
