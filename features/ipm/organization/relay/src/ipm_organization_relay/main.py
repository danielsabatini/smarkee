"""Entrypoint do relay de Organization (`ipm-organization-relay`, decisão 0015).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o relay do outbox.
"""

import asyncio
import logging
import signal
import sys

from ipm_organization_relay.logging_config import configure_logging
from ipm_organization_relay.nats import JetStreamPublisher, connect, jetstream_of
from ipm_organization_relay.relay import OutboxRelay
from ipm_organization_relay.settings import OrganizationRelaySettings, missing_required

EXIT_INVALID_CONFIGURATION = 2

logger = logging.getLogger(__name__)


async def run(settings: OrganizationRelaySettings) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop.set)

    nats_client = await connect(settings.nats)
    publisher = JetStreamPublisher(jetstream_of(nats_client))
    relay = asyncio.create_task(OutboxRelay(settings.database, publisher).run(stop))
    logger.info("organization relay started")
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({waiter, relay}, return_when=asyncio.FIRST_COMPLETED)

    exit_code = 1 if relay in done else 0
    if exit_code:
        logger.error("relay stopped unexpectedly")
    stop.set()
    result = (await asyncio.gather(relay, return_exceptions=True))[0]
    if isinstance(result, BaseException):
        logger.error("relay failed", extra={"error_type": type(result).__name__})
        exit_code = 1
    waiter.cancel()
    await nats_client.drain()
    return exit_code


def main() -> None:
    configure_logging()
    settings = OrganizationRelaySettings()
    missing = missing_required(settings)
    if missing:
        logger.error("missing required configuration", extra={"variables": missing})
        sys.exit(EXIT_INVALID_CONFIGURATION)
    sys.exit(asyncio.run(run(settings)))


if __name__ == "__main__":
    main()
