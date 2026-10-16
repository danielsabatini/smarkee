"""Entrypoint do Manager de Account (`core-account-manager`, decisões 0015 e 0019).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import asyncio
import logging
import signal
import sys

from core_account_manager.domain.kind import account_kind
from core_account_manager.handlers.observed import ObservedHandler
from core_account_manager.handlers.requested import RequestedHandler
from core_account_manager.handlers.result import ResultHandler
from core_account_manager.http.health import Health, serve_health
from core_account_manager.logging_config import configure_logging
from core_account_manager.settings import AccountManagerSettings, missing_required
from core_account_manager.store.database import open_pool
from core_account_manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)
from core_account_manager.transport.nats import connect, jetstream_of

EXIT_INVALID_CONFIGURATION = 2

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


async def run(settings: AccountManagerSettings) -> int:
    stop = _stop_on_signals()
    health = Health()
    nats_client = await connect(settings.nats)
    pool = await open_pool(settings.database)
    jetstream = jetstream_of(nats_client)
    account = account_kind(settings.platform.roles)
    health.add_check("nats", lambda: nats_client.is_connected)
    consumers = {
        "requested": RequestedConsumer(
            jetstream, pool, account, handler=RequestedHandler(), on_cycle=health.beat
        ),
        "observed": ObservedConsumer(
            jetstream, pool, account, handler=ObservedHandler(), on_cycle=health.beat
        ),
        "result": ResultConsumer(
            jetstream,
            pool,
            account,
            handler=ResultHandler(failure_limit=settings.loop.failure_limit),
            on_cycle=health.beat,
        ),
    }
    tasks = {name: asyncio.create_task(consumer.run(stop)) for name, consumer in consumers.items()}
    tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
    health.mark_started()
    logger.info("account manager started")
    exit_code = await _run_until_stopped(tasks, stop)
    await nats_client.drain()
    await pool.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = AccountManagerSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
