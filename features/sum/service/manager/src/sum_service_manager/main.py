"""Entrypoint do Manager de `sum.service` (`sum-service-manager`, decisões 0015 e 0033).

Consome `requested` e escreve no SSOT; só insere no outbox. A publicação do outbox é do Publisher,
que é outro processo. Só inicializa e encerra: valida a configuração, abre as conexões e roda o
consumer.
"""

import asyncio
import logging
import signal
import sys

from sum_service_manager.database import open_pool
from sum_service_manager.domain.service import CatalogError, parse_catalog
from sum_service_manager.handlers.requested import RequestedHandler
from sum_service_manager.http.health import Health, serve_health
from sum_service_manager.logging_config import configure_logging
from sum_service_manager.settings import SumServiceManagerSettings, missing_required
from sum_service_manager.transport.nats import connect, jetstream_of
from sum_service_manager.transport.requested import Disposition, RequestedConsumer
from sum_service_manager.transport.state import (
    process_account_removed,
    process_observed,
    process_result,
    run_consumer,
)

EXIT_INVALID_CONFIGURATION = 2
DURABLE_REQUESTED = "sum-service-manager-requested"
DURABLE_OBSERVED = "sum-service-manager-observed"
DURABLE_COMPLETED = "sum-service-manager-completed"
DURABLE_FAILED = "sum-service-manager-failed"
DURABLE_ACCOUNT_REMOVED = "sum-service-manager-account-removed"

logger = logging.getLogger(__name__)


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)
    return stop


async def _run_until_stopped(tasks: dict[str, asyncio.Task[None]], stop: asyncio.Event) -> int:
    """Espera o sinal de parada ou o fim inesperado de uma tarefa; encerra todas."""
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({waiter, *tasks.values()}, return_when=asyncio.FIRST_COMPLETED)
    exit_code = 0
    if not stop.is_set():
        # Fim sem pedido de parada: uma tarefa caiu, e o processo sai com erro.
        for name, task in tasks.items():
            if task in done:
                exit_code = 1
                logger.error("task stopped unexpectedly", extra={"task": name})
    stop.set()
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("task failed", extra={"task": name, "error_type": type(result).__name__})
            exit_code = 1
    waiter.cancel()
    return exit_code


async def run(settings: SumServiceManagerSettings) -> int:
    stop = _stop_on_signals()
    health = Health()
    catalog = parse_catalog(settings.catalog.roles or "")
    nats_client = await connect(settings.nats.url, settings.nats.user, settings.nats.password)
    pool = await open_pool(settings.database)
    health.add_check("nats", lambda: nats_client.is_connected)
    consumer = RequestedConsumer(
        jetstream_of(nats_client),
        pool,
        RequestedHandler(catalog=catalog),
        durable_name=DURABLE_REQUESTED,
        on_cycle=health.beat,
    )
    jetstream = jetstream_of(nats_client)

    async def handle_observed(data: bytes) -> Disposition:
        return await process_observed(pool, data)

    async def handle_completed(data: bytes) -> Disposition:
        return await process_result(pool, data, "completed")

    async def handle_failed(data: bytes) -> Disposition:
        return await process_result(pool, data, "failed")

    async def handle_account_removed(data: bytes) -> Disposition:
        return await process_account_removed(pool, data)

    tasks = {
        "requested": asyncio.create_task(consumer.run(stop)),
        "observed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="OBSERVED",
                durable=DURABLE_OBSERVED,
                handle=handle_observed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "completed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="RESULT",
                durable=DURABLE_COMPLETED,
                handle=handle_completed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "failed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="RESULT",
                durable=DURABLE_FAILED,
                handle=handle_failed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "account_removed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="UPDATED",
                durable=DURABLE_ACCOUNT_REMOVED,
                handle=handle_account_removed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "health": asyncio.create_task(serve_health(health, settings.health.port, stop)),
    }
    health.mark_started()
    logger.info("sum service manager started")
    exit_code = await _run_until_stopped(tasks, stop)
    # As tarefas já terminaram: nada está em processamento. Uma mensagem não confirmada volta pelo
    # `ack_wait` do consumer, por isso `close()` basta (o `drain()` esperava o tempo limite).
    await nats_client.close()
    await pool.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = SumServiceManagerSettings()
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
