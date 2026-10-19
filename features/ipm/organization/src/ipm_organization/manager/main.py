"""Entrypoint do Manager de Organization (`ipm-organization-manager`, decisões 0015, 0019 e 0063).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import asyncio
import logging

from ipm_organization.common.database import open_pool
from ipm_organization.common.http.health import Health, serve_health
from ipm_organization.common.lifecycle import start_role, stop_on_signals, supervise
from ipm_organization.common.messaging import connect, stream_of
from ipm_organization.manager.domain.kind import ORGANIZATION
from ipm_organization.manager.handlers.observed import ObservedHandler
from ipm_organization.manager.handlers.requested import RequestedHandler
from ipm_organization.manager.handlers.result import ResultHandler
from ipm_organization.manager.settings import OrganizationManagerSettings, missing_required
from ipm_organization.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

logger = logging.getLogger(__name__)


async def run(settings: OrganizationManagerSettings) -> int:
    stop = stop_on_signals()
    health = Health()
    messaging_client = await connect(settings.nats, name="ipm-organization-manager")
    pool = await open_pool(settings.database)
    jetstream = stream_of(messaging_client)
    organization = ORGANIZATION
    health.add_check("nats", lambda: messaging_client.is_connected)
    consumers = {
        "requested": RequestedConsumer(
            jetstream, pool, organization, handler=RequestedHandler(), on_cycle=health.beat
        ),
        "observed": ObservedConsumer(
            jetstream, pool, organization, handler=ObservedHandler(), on_cycle=health.beat
        ),
        "result": ResultConsumer(
            jetstream,
            pool,
            organization,
            handler=ResultHandler(failure_limit=settings.loop.failure_limit),
            on_cycle=health.beat,
        ),
    }
    tasks = {name: asyncio.create_task(consumer.run(stop)) for name, consumer in consumers.items()}
    tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
    health.mark_started()
    logger.info("organization manager started")
    exit_code = await supervise(tasks, stop)
    await messaging_client.drain()
    await pool.close()
    return exit_code


def main() -> None:
    start_role("manager", OrganizationManagerSettings, missing_required, run)


if __name__ == "__main__":
    main()
