"""Entrypoint do Publisher de `sum.service` (`sum-service-publisher`, decisões 0015 e 0033).

Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher. Uma recusa
permanente não derruba o processo: o Publisher sai de `ready` e quem opera é avisado (decisão 0018).
"""

import asyncio
import logging
import signal
import sys

from sum_service_publisher.http.health import Health, serve_health
from sum_service_publisher.logging_config import configure_logging
from sum_service_publisher.outbox.publication import OutboxPublisher
from sum_service_publisher.settings import SumServicePublisherSettings, missing_required
from sum_service_publisher.transport.nats import connect, jetstream_of
from sum_service_publisher.transport.publisher import JetStreamPublisher

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: SumServicePublisherSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    health = Health()
    nats_client = await connect(settings.nats.url, settings.nats.user, settings.nats.password)
    publisher = OutboxPublisher(
        settings.database, JetStreamPublisher(jetstream_of(nats_client)), on_cycle=health.beat
    )
    health.add_check("nats", lambda: nats_client.is_connected)
    health.add_check("publication", lambda: not publisher.blocked_by_permanent_failure)
    tasks = {
        "publisher": asyncio.create_task(publisher.run(stop)),
        "health": asyncio.create_task(serve_health(health, settings.health.port, stop)),
    }
    health.mark_started()
    logger.info("sum service publisher started")
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({waiter, *tasks.values()}, return_when=asyncio.FIRST_COMPLETED)

    exit_code = 0
    for name, task in tasks.items():
        # Só é falha uma tarefa que terminou sem que a parada tenha sido pedida.
        if task in done and not stop.is_set():
            exit_code = 1
            logger.error("task stopped unexpectedly", extra={"smarkee.task.name": name})
    stop.set()
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("task failed", extra={"smarkee.task.name": name}, exc_info=result)
            exit_code = 1
    waiter.cancel()
    await nats_client.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = SumServicePublisherSettings()
    missing = missing_required(settings)
    if missing:
        logger.error(
            "missing required configuration", extra={"smarkee.config.missing_variables": missing}
        )
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
