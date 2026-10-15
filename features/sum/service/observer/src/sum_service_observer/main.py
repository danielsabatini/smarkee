"""Entrypoint do Observer de `sum.service` (`sum-service-observer`, decisões 0015 e 0033).

Lê o Zitadel só de leitura e publica `observed`. Consome o `desired` (para saber o que observar)
e os resultados (para observar depois de cada ação), e observa periodicamente. Só inicializa e
encerra.
"""

import asyncio
import logging
import signal
import sys

import httpx

from sum_service_observer.domain.service import CatalogError, parse_catalog
from sum_service_observer.engine.observer import Observer
from sum_service_observer.http.health import Health, serve_health
from sum_service_observer.logging_config import configure_logging
from sum_service_observer.provider.zitadel import ZitadelReader
from sum_service_observer.settings import SumServiceObserverSettings, missing_required
from sum_service_observer.transport.consumers import PullConsumer
from sum_service_observer.transport.nats import JetStreamPublisher, connect, jetstream_of

EXIT_INVALID_CONFIGURATION = 2
CONSUMERS = (
    ("DESIRED", "sum-service-observer-desired"),
    ("RESULT", "sum-service-observer-completed"),
    ("RESULT", "sum-service-observer-failed"),
)

logger = logging.getLogger(__name__)


async def _observe_periodically(observer: Observer, interval: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            await observer.observe_all()


async def run(settings: SumServiceObserverSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    catalog = parse_catalog(settings.catalog.roles or "")
    health = Health()
    nats_client = await connect(settings.nats.url, settings.nats.user, settings.nats.password)
    jetstream = jetstream_of(nats_client)
    health.add_check("nats", lambda: nats_client.is_connected)
    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as client:
        reader = ZitadelReader(settings.zitadel, client)
        observer = Observer(reader, JetStreamPublisher(jetstream), catalog)

        async def handle(data: bytes) -> object:
            return await observer.on_message(data)

        tasks = [
            asyncio.create_task(
                PullConsumer(
                    jetstream, stream=stream, durable=durable, handle=handle, on_cycle=health.beat
                ).run(stop)
            )
            for stream, durable in CONSUMERS
        ]
        tasks.append(
            asyncio.create_task(
                _observe_periodically(observer, settings.loop.observation_interval_seconds, stop)
            )
        )
        tasks.append(asyncio.create_task(serve_health(health, settings.health.port, stop)))
        health.mark_started()
        logger.info("sum service observer started")
        await stop.wait()
        await asyncio.gather(*tasks, return_exceptions=True)
    await nats_client.close()
    return 0


def main() -> None:
    configure_logging()
    settings = SumServiceObserverSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        logger.error("invalid service catalog", extra={"reason": str(error)})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
