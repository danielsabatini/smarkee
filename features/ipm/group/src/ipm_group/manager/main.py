"""Entrypoint do Manager de Grupo (`ipm-group-manager`, decisões 0015, 0019, 0063 e 0088).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.catalog_watcher import RoleCatalogWatcher
from ipm_group.common.database import open_pool
from ipm_group.common.lifecycle import start_role
from ipm_group.common.messaging import StateConsumer, new_instance_name
from ipm_group.common.runtime import role_runtime
from ipm_group.manager.domain.group import GroupPolicy
from ipm_group.manager.domain.kind import ResourceKind
from ipm_group.manager.handlers.observed import ObservedHandler
from ipm_group.manager.handlers.requested import RequestedHandler
from ipm_group.manager.handlers.result import ResultHandler
from ipm_group.manager.settings import GroupManagerSettings, missing_required
from ipm_group.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

logger = logging.getLogger(__name__)


async def run(settings: GroupManagerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-group-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        # A regra `invalid` precisa conhecer as Roles `custom` das Organizations (decisão 0092).
        catalog = RolesCatalog()
        kind = ResourceKind(resource_type="group", policy=GroupPolicy(catalog))
        watcher = RoleCatalogWatcher(catalog)
        instance = new_instance_name()
        consumers = {
            "requested": RequestedConsumer(
                runtime.stream,
                pool,
                kind,
                handler=RequestedHandler(),
                on_cycle=runtime.health.beat,
            ),
            "observed": ObservedConsumer(
                runtime.stream,
                pool,
                kind,
                handler=ObservedHandler(
                    progress_deadline_seconds=settings.loop.progress_deadline_seconds
                ),
                on_cycle=runtime.health.beat,
            ),
            "result": ResultConsumer(
                runtime.stream,
                pool,
                kind,
                handler=ResultHandler(failure_limit=settings.loop.failure_limit),
                on_cycle=runtime.health.beat,
            ),
            "roles": StateConsumer(
                runtime.stream,
                watcher,
                durable=f"ipm-group-manager-roles-{instance}",
                stream="DESIRED",
                filter_subject="manager.desired.ipm.role.>",
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            ),
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("group manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("manager", GroupManagerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
