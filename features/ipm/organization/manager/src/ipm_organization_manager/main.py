"""Entrypoint do Manager de Organization (`srv-ipm-organization-manager`, decisão 0015).

Só inicializa e encerra: valida a configuração, abre as conexões e roda o consumer de `requested`.
"""

import asyncio
import logging
import signal
import sys

from ipm_organization_manager.database import open_pool
from ipm_organization_manager.kind import ORGANIZATION
from ipm_organization_manager.logging_config import configure_logging
from ipm_organization_manager.messaging import RequestedConsumer, connect, jetstream_of
from ipm_organization_manager.settings import OrganizationManagerSettings, missing_required

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: OrganizationManagerSettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    nats_client = await connect(settings.nats)
    pool = await open_pool(settings.database)
    consumer = asyncio.create_task(
        RequestedConsumer(jetstream_of(nats_client), pool, ORGANIZATION).run(stop)
    )
    logger.info("organization manager started")
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({waiter, consumer}, return_when=asyncio.FIRST_COMPLETED)

    exit_code = 1 if consumer in done else 0
    if exit_code:
        logger.error("consumer stopped unexpectedly")
    stop.set()
    result = (await asyncio.gather(consumer, return_exceptions=True))[0]
    if isinstance(result, BaseException):
        logger.error("consumer failed", extra={"error_type": type(result).__name__})
        exit_code = 1
    waiter.cancel()
    await nats_client.drain()
    await pool.close()
    return exit_code


def main() -> None:
    configure_logging()
    settings = OrganizationManagerSettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
