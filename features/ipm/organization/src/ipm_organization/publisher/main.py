"""Entrypoint do Publisher de Organization (`ipm-organization-publisher`, decisões 0015, 0019).

Lê o outbox do tipo e publica no transporte, em ordem; uma instância ativa por trava consultiva.
Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o Publisher.
"""

import asyncio
import logging

from ipm_organization.common.http.health import Health, serve_health
from ipm_organization.common.lifecycle import start_role, stop_on_signals, supervise
from ipm_organization.common.messaging import JetStreamPublisher, connect, jetstream_of
from ipm_organization.publisher.outbox.publication import OutboxPublisher
from ipm_organization.publisher.settings import OrganizationPublisherSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: OrganizationPublisherSettings) -> int:
    stop = stop_on_signals()
    health = Health()
    nats_client = await connect(settings.nats, name="ipm-organization-publisher")
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
    logger.info("organization publisher started")
    exit_code = await supervise(tasks, stop)
    await nats_client.drain()
    return exit_code


def main() -> None:
    start_role("publisher", OrganizationPublisherSettings, missing_required, run)


if __name__ == "__main__":
    main()
