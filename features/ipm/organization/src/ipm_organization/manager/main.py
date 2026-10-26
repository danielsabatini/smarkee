"""Entrypoint do Manager de Organization (`ipm-organization-manager`, decisões 0015, 0019 e 0063).

Consome `requested`, `observed` e `completed`/`failed` e escreve no SSOT; só insere no outbox. A
publicação do outbox é do Publisher (`../publisher`). Só inicializa e encerra: valida a
configuração, abre as conexões e roda os consumers.
"""

import logging
import sys

from ipm_organization.common.database import open_pool
from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import StateConsumer, new_instance_name
from ipm_organization.common.runtime import role_runtime
from ipm_organization.common.user_access import desired_user_access
from ipm_organization.manager.domain.kind import organization_kind
from ipm_organization.manager.handlers.observed import ObservedHandler
from ipm_organization.manager.handlers.requested import RequestedHandler
from ipm_organization.manager.handlers.result import ResultHandler
from ipm_organization.manager.handlers.user_access_rollout import (
    PermissionCatalogWatcher,
    roll_out_user_access,
)
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
        kind = organization_kind(_user_access(settings))
        # Antes dos consumers: toda Organization fica com o `userAccess` de agora (decisão 0081).
        await roll_out_user_access(pool, kind)
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
            "permissions": StateConsumer(
                runtime.stream,
                PermissionCatalogWatcher(pool, kind),
                durable=f"ipm-organization-manager-permissions-{instance}",
                stream="DESIRED",
                filter_subject="manager.desired.ipm.permission.>",
                inactive_threshold_seconds=300,
                traced=False,
                on_cycle=runtime.health.beat,
            ),
        }
        for name, consumer in consumers.items():
            runtime.start(name, consumer.run(runtime.stop))
        logger.info("organization manager started")
        return await runtime.serve(health_port=settings.health.port)


def _user_access(settings: OrganizationManagerSettings) -> dict[str, object]:
    executor = settings.user_access.user_executor_account_id
    observer = settings.user_access.user_observer_account_id
    machine_executor = settings.user_access.serviceaccount_executor_account_id
    machine_observer = settings.user_access.serviceaccount_observer_account_id
    assert executor and observer  # noqa: S101 (garantido por `missing_required`)
    assert machine_executor and machine_observer  # noqa: S101 (idem)
    return desired_user_access(
        user_executor_account_id=executor,
        user_observer_account_id=observer,
        serviceaccount_executor_account_id=machine_executor,
        serviceaccount_observer_account_id=machine_observer,
    )


def main() -> None:
    start_role("manager", OrganizationManagerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
