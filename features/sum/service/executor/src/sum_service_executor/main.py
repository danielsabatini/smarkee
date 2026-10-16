"""Entrypoint do Executor de `sum.service` (`sum-service-executor`, decisões 0015, 0032 e 0033).

Consome uma partição do Stream `ACTION`, executa cada `action` no Zitadel (único componente com
escrita de
roles de serviço) e publica `completed` ou `failed`. Só inicializa e encerra.
"""

import asyncio
import logging
import signal
import sys

import httpx

from sum_service_executor.domain.service import CatalogError, parse_catalog
from sum_service_executor.engine.executor import Executor
from sum_service_executor.http.health import Health, serve_health
from sum_service_executor.logging_config import configure_logging
from sum_service_executor.provider.zitadel import ZitadelGranter
from sum_service_executor.settings import SumServiceExecutorSettings, missing_required
from sum_service_executor.transport.consumers import PullConsumer
from sum_service_executor.transport.nats import (
    DirectStateReader,
    JetStreamPublisher,
    connect,
    jetstream_of,
)

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: SumServiceExecutorSettings) -> int:
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
        granter = ZitadelGranter(settings.zitadel, client)
        executor = Executor(
            granter,
            DirectStateReader(jetstream),
            JetStreamPublisher(jetstream),
            catalog,
        )

        async def handle(data: bytes) -> object:
            return await executor.on_action(data)

        # Um consumer e um laço por partição, como no Executor do User (decisão 0018): uma ação
        # por vez em cada recurso, e até `count` recursos em paralelo.
        consumers = [
            PullConsumer(
                jetstream,
                stream="ACTION",
                durable=f"sum-service-executor-action-p{partition}",
                handle=handle,
                on_cycle=health.beat,
            )
            for partition in range(settings.partition.count)
        ]
        tasks = [asyncio.create_task(consumer.run(stop)) for consumer in consumers]
        tasks.append(asyncio.create_task(serve_health(health, settings.health.port, stop)))
        health.mark_started()
        logger.info(
            "sum service executor started",
            extra={"smarkee.partition.count": settings.partition.count},
        )
        await stop.wait()
        await asyncio.gather(*tasks, return_exceptions=True)
    await nats_client.close()
    return 0


def main() -> None:
    configure_logging()
    settings = SumServiceExecutorSettings()
    missing = missing_required(settings)
    if missing:
        logger.error(
            "missing required configuration", extra={"smarkee.config.missing_variables": missing}
        )
        sys.exit(EXIT_INVALID_CONFIGURATION)
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        logger.error("invalid service catalog", extra={"smarkee.reason": str(error)})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
