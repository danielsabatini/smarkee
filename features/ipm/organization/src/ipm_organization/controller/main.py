"""Entrypoint do Controller de Organization (`ipm-organization-controller`, decisão 0096).

Unifica observação, decisão pura e execução idempotente com padrão Informer + Workqueue.
"""

import logging
import sys
from collections.abc import Sequence

import httpx

from ipm_organization.common.database import open_pool
from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import StateConsumer, new_instance_name
from ipm_organization.common.runtime import role_runtime
from ipm_organization.controller.drivers.identity import IdentityConnection
from ipm_organization.controller.drivers.metadata import MetadataDriver
from ipm_organization.controller.drivers.organization import OrganizationDriver
from ipm_organization.controller.drivers.user_access import UserAccessDriver
from ipm_organization.controller.engine.controller import ControllerDrivers, OrganizationController
from ipm_organization.controller.settings import OrganizationControllerSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: OrganizationControllerSettings) -> int:
    instance = new_instance_name()

    async with (
        role_runtime(settings.messaging, name=f"ipm-organization-controller-{instance}") as runtime,
        httpx.AsyncClient(timeout=settings.identity.timeout_seconds) as client,
    ):
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        connection = IdentityConnection(settings.identity, client)
        drivers = ControllerDrivers(
            organizations=OrganizationDriver(connection),
            metadata=MetadataDriver(connection),
            user_access=UserAccessDriver(connection, str(settings.identity.project_id)),
        )

        controller = OrganizationController(pool, drivers, settings)
        runtime.close_after(controller.shutdown)

        # Informer do stream DESIRED
        consumer = StateConsumer(
            runtime.stream,
            controller,
            durable=f"ipm-organization-controller-desired-{instance}",
            stream="DESIRED",
            filter_subject="manager.desired.ipm.organization.>",
            inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
            traced=False,
            on_cycle=runtime.health.beat,
        )

        # Inicia o Informer (StateConsumer)
        runtime.start("desired", consumer.run(runtime.stop))

        # Inicia os workers
        for worker_id in range(settings.loop.workers):
            runtime.start(f"worker-{worker_id}", controller.run_worker(worker_id))

        # Inicia a reavaliação periódica
        runtime.start("periodic", controller.run_periodic_reevaluation())

        logger.info(
            "organization controller started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main(argv: Sequence[str] = ()) -> None:
    start_role(
        "controller",
        OrganizationControllerSettings,
        missing_required,
        run,
        cli_args=argv or sys.argv[1:],
    )


if __name__ == "__main__":
    main()
