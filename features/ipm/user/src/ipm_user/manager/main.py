"""Entrypoint do Manager de User (`ipm-user-manager`, decisões 0015, 0019 e 0063).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from ipm_user.common.database import open_pool
from ipm_user.common.lifecycle import start_role
from ipm_user.common.messaging import StateConsumer, new_instance_name
from ipm_user.common.runtime import role_runtime
from ipm_user.manager.domain.kind import user_kind
from ipm_user.manager.handlers.observed import ObservedHandler
from ipm_user.manager.handlers.requested import RequestedHandler
from ipm_user.manager.handlers.result import ResultHandler
from ipm_user.manager.handlers.role_rollout import RoleCatalogWatcher
from ipm_user.manager.settings import UserManagerSettings, missing_required
from ipm_user.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

logger = logging.getLogger(__name__)


async def run(settings: UserManagerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-user-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        kind = user_kind()
        catalog_consumers: dict[str, StateConsumer] = {}

        def is_catalog_synced() -> bool:
            return bool(catalog_consumers) and all(c.is_synced for c in catalog_consumers.values())

        watcher = RoleCatalogWatcher(
            pool,
            kind,
            is_synced=is_catalog_synced,
            debounce_seconds=0.2,
        )
        instance = new_instance_name()
        catalog_consumers["permissions"] = StateConsumer(
            runtime.stream,
            watcher,
            durable=f"ipm-user-manager-permissions-{instance}",
            stream="DESIRED",
            filter_subject="manager.desired.ipm.permission.>",
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        catalog_consumers["roles"] = StateConsumer(
            runtime.stream,
            watcher,
            durable=f"ipm-user-manager-roles-{instance}",
            stream="DESIRED",
            filter_subject="manager.desired.ipm.role.>",
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        catalog_consumers["groups"] = StateConsumer(
            runtime.stream,
            watcher,
            durable=f"ipm-user-manager-groups-{instance}",
            stream="DESIRED",
            filter_subject="manager.desired.ipm.group.>",
            inactive_threshold_seconds=300,
            traced=False,
            on_cycle=runtime.health.beat,
        )
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
            **catalog_consumers,
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("user manager started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("manager", UserManagerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
