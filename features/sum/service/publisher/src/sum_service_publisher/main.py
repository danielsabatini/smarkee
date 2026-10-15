"""Entrypoint do Publisher de `sum.service` (`sum-service-publisher`, decisões 0015 e 0033).

Lê o outbox do SSOT e publica no NATS (`manager.desired.sum.service.<resourceId>.changed`), marcando
`published_at` só depois da confirmação. É o único processo com o papel de leitura do outbox. Uma
mensagem fora do envelope para o laço e o processo sai com erro: quem opera decide o que fazer.
"""

import asyncio
import logging
import signal
import sys
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from sum_service_publisher.database import conninfo
from sum_service_publisher.http.health import Health, serve_health
from sum_service_publisher.logging_config import configure_logging
from sum_service_publisher.outbox.publication import (
    PublicationRejectedError,
    PublishError,
    publish_pending,
)
from sum_service_publisher.settings import SumServicePublisherSettings, missing_required
from sum_service_publisher.transport.nats import connect, jetstream_of
from sum_service_publisher.transport.publisher import JetStreamPublisher

EXIT_INVALID_CONFIGURATION = 2
EXIT_PUBLICATION_STOPPED = 1
POLL_INTERVAL_SECONDS = 0.5
BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)

logger = logging.getLogger(__name__)


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    return stop


async def run_loop(
    connection: psycopg.AsyncConnection[Any],
    publisher: JetStreamPublisher,
    stop: asyncio.Event,
    health: Health,
) -> int:
    """Publica até receber o sinal de parada. Erro permanente para o laço e devolve código 1."""
    backoff = iter(BACKOFF_SECONDS)
    while not stop.is_set():
        health.beat()
        try:
            published = await publish_pending(connection, publisher)
            backoff = iter(BACKOFF_SECONDS)
            if published == 0:
                await _wait(stop, POLL_INTERVAL_SECONDS)
        except PublicationRejectedError as error:
            logger.error("outbox message rejected", extra={"reason": str(error)})
            return EXIT_PUBLICATION_STOPPED
        except PublishError as error:
            if error.permanent:
                logger.error("publication refused permanently", extra={"reason": str(error)})
                return EXIT_PUBLICATION_STOPPED
            delay = next(backoff, BACKOFF_SECONDS[-1])
            logger.warning(
                "publication failed; retrying", extra={"error": str(error), "delay": delay}
            )
            await _wait(stop, delay)
    return 0


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return


async def run(settings: SumServicePublisherSettings) -> int:
    stop = _stop_on_signals()
    health = Health()
    nats_client = await connect(settings.nats.url, settings.nats.user, settings.nats.password)
    connection: psycopg.AsyncConnection[Any] = await psycopg.AsyncConnection.connect(
        conninfo(settings.database), autocommit=True, row_factory=tuple_row
    )
    health.add_check("nats", lambda: nats_client.is_connected)
    health_task = asyncio.create_task(serve_health(health, settings.health.port, stop))
    health.mark_started()
    logger.info("sum service publisher started")
    try:
        exit_code = await run_loop(
            connection, JetStreamPublisher(jetstream_of(nats_client)), stop, health
        )
    finally:
        stop.set()
        await health_task
        await nats_client.close()
        await connection.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = SumServicePublisherSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
