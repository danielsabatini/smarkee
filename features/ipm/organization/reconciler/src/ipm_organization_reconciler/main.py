"""Entrypoint do Reconciler de Organization (`ipm-organization-reconciler`, decisão 0015).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import asyncio
import logging
import signal
import sys

from ipm_organization_reconciler.engine.reconciler import Reconciler
from ipm_organization_reconciler.http.health import Health, serve_health
from ipm_organization_reconciler.logging_config import configure_logging
from ipm_organization_reconciler.settings import OrganizationReconcilerSettings, missing_required
from ipm_organization_reconciler.transport.nats import (
    STREAMS,
    JetStreamPublisher,
    StateConsumer,
    connect,
    jetstream_of,
    new_instance_name,
    periodic_reevaluation,
)

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: OrganizationReconcilerSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    nats_client = await connect(settings.nats)
    jetstream = jetstream_of(nats_client)
    health = Health()
    health.add_check("nats", lambda: nats_client.is_connected)
    reconciler = Reconciler(JetStreamPublisher(jetstream), settings.loop)
    instance = new_instance_name()
    tasks = {
        suffix: asyncio.create_task(
            StateConsumer(
                jetstream,
                reconciler,
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
        periodic_reevaluation(reconciler, settings.loop, stop, on_cycle=health.beat)
    )
    tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
    health.mark_started()
    logger.info("organization reconciler started", extra={"smarkee.instance.name": instance})
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({waiter, *tasks.values()}, return_when=asyncio.FIRST_COMPLETED)

    exit_code = 0
    for name, task in tasks.items():
        if task in done:
            exit_code = 1
            logger.error("task stopped unexpectedly", extra={"smarkee.task.name": name})
    stop.set()
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for name, result in zip(tasks, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("task failed", extra={"smarkee.task.name": name}, exc_info=result)
            exit_code = 1
    waiter.cancel()
    await nats_client.drain()
    return exit_code


def main() -> None:
    configure_logging()
    settings = OrganizationReconcilerSettings()
    missing = missing_required(settings)
    if missing:
        logger.error(
            "missing required configuration", extra={"smarkee.config.missing_variables": missing}
        )
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
