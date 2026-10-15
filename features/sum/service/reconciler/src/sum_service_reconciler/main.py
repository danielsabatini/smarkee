"""Entrypoint do Reconciler de `sum.service` (`sum-service-reconciler`, decisões 0015 e 0033).

Consome `desired`, `observed` e os resultados (`completed` e `failed`), decide e publica as
`action` no stream `ACTION`. Só inicializa e encerra: valida a configuração, abre a conexão e
roda os laços.
"""

import asyncio
import logging
import signal
import sys

from sum_service_reconciler.engine.reconciler import Reconciler
from sum_service_reconciler.http.health import Health, serve_health
from sum_service_reconciler.logging_config import configure_logging
from sum_service_reconciler.settings import ReconcilerSettings, missing_required
from sum_service_reconciler.transport.consumers import PullConsumer
from sum_service_reconciler.transport.nats import JetStreamPublisher, connect, jetstream_of

EXIT_INVALID_CONFIGURATION = 2
EVALUATION_INTERVAL_SECONDS = 15.0

logger = logging.getLogger(__name__)

CONSUMERS = (
    ("DESIRED", "sum-service-reconciler-desired"),
    ("OBSERVED", "sum-service-reconciler-observed"),
    ("RESULT", "sum-service-reconciler-completed"),
    ("RESULT", "sum-service-reconciler-failed"),
)


async def _evaluate_periodically(reconciler: Reconciler, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await reconciler.evaluate_all()
        try:
            await asyncio.wait_for(stop.wait(), timeout=EVALUATION_INTERVAL_SECONDS)
        except TimeoutError:
            continue


async def run(settings: ReconcilerSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    health = Health()
    nats_client = await connect(settings.nats.url, settings.nats.user, settings.nats.password)
    jetstream = jetstream_of(nats_client)
    reconciler = Reconciler(JetStreamPublisher(jetstream), settings.loop)
    health.add_check("nats", lambda: nats_client.is_connected)

    async def handle(data: bytes) -> object:
        return await reconciler.on_message(data)

    tasks = [
        asyncio.create_task(
            PullConsumer(
                jetstream,
                stream=stream,
                durable=durable,
                handle=handle,
                on_cycle=health.beat,
            ).run(stop)
        )
        for stream, durable in CONSUMERS
    ]
    tasks.append(asyncio.create_task(_evaluate_periodically(reconciler, stop)))
    tasks.append(asyncio.create_task(serve_health(health, settings.health.port, stop)))
    health.mark_started()
    logger.info("sum service reconciler started")
    await stop.wait()
    await asyncio.gather(*tasks, return_exceptions=True)
    await nats_client.close()
    return 0


def main() -> None:
    configure_logging()
    settings = ReconcilerSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
