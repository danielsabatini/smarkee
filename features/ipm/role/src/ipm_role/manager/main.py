"""Entrypoint do Manager de Role (`ipm-role-manager`, decisões 0015, 0019, 0063 e 0083).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from ipm_role.common.database import open_pool
from ipm_role.common.lifecycle import start_role
from ipm_role.common.runtime import role_runtime
from ipm_role.manager.domain.kind import ROLE
from ipm_role.manager.handlers.observed import ObservedHandler
from ipm_role.manager.handlers.requested import RequestedHandler
from ipm_role.manager.handlers.result import ResultHandler
from ipm_role.manager.settings import RoleManagerSettings, missing_required
from ipm_role.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

logger = logging.getLogger(__name__)


async def run(settings: RoleManagerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-role-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        consumers = {
            "requested": RequestedConsumer(
                runtime.stream,
                pool,
                ROLE,
                handler=RequestedHandler(),
                on_cycle=runtime.health.beat,
            ),
            "observed": ObservedConsumer(
                runtime.stream,
                pool,
                ROLE,
                handler=ObservedHandler(
                    progress_deadline_seconds=settings.loop.progress_deadline_seconds
                ),
                on_cycle=runtime.health.beat,
            ),
            "result": ResultConsumer(
                runtime.stream,
                pool,
                ROLE,
                handler=ResultHandler(failure_limit=settings.loop.failure_limit),
                on_cycle=runtime.health.beat,
            ),
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("role manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("manager", RoleManagerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
