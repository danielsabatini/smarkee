"""Entrypoint do Manager de Organization (`ipm-organization-manager`, decisões 0015, 0019 e 0063).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging

from ipm_organization.common.database import open_pool
from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.runtime import role_runtime
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
    async with role_runtime(settings.messaging, name="ipm-organization-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        consumers = {
            "requested": RequestedConsumer(
                runtime.stream,
                pool,
                ORGANIZATION,
                handler=RequestedHandler(),
                on_cycle=runtime.health.beat,
            ),
            "observed": ObservedConsumer(
                runtime.stream,
                pool,
                ORGANIZATION,
                handler=ObservedHandler(),
                on_cycle=runtime.health.beat,
            ),
            "result": ResultConsumer(
                runtime.stream,
                pool,
                ORGANIZATION,
                handler=ResultHandler(failure_limit=settings.loop.failure_limit),
                on_cycle=runtime.health.beat,
            ),
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("organization manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("manager", OrganizationManagerSettings, missing_required, run)


if __name__ == "__main__":
    main()
