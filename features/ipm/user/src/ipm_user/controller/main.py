"""Entrypoint do Controller do usuário da Organization (`ipm-user-controller`, decisão 0096).

Unifica observação, decisão pura e execução idempotente com padrão Informer + Workqueue.
"""

import logging
import sys
from collections.abc import Sequence

import httpx

from ipm_user.common.database import open_pool
from ipm_user.common.lifecycle import start_role
from ipm_user.common.messaging import StateConsumer, new_instance_name
from ipm_user.common.runtime import role_runtime
from ipm_user.controller.drivers.authorization import AuthorizationDriver
from ipm_user.controller.drivers.identity import IdentityConnection
from ipm_user.controller.drivers.metadata import MetadataDriver
from ipm_user.controller.drivers.user import UserDriver
from ipm_user.controller.engine.controller import (
    ControllerDrivers,
    UserController,
)
from ipm_user.controller.settings import (
    UserControllerSettings,
    missing_required,
)

logger = logging.getLogger(__name__)


async def run(settings: UserControllerSettings) -> int:
    instance = new_instance_name()

    async with (
        role_runtime(settings.messaging, name=f"ipm-user-controller-{instance}") as runtime,
        httpx.AsyncClient(timeout=settings.identity.timeout_seconds) as client,
    ):
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        connection = IdentityConnection(settings.identity, client)
        drivers = ControllerDrivers(
            users=UserDriver(connection),
            authorizations=AuthorizationDriver(connection, str(settings.identity.project_id)),
            metadata=MetadataDriver(connection),
        )

        controller = UserController(pool, drivers, settings)
        runtime.close_after(controller.shutdown)

        # Informer do stream DESIRED
        consumer = StateConsumer(
            runtime.stream,
            controller,
            durable=f"ipm-user-controller-desired-{instance}",
            stream="DESIRED",
            filter_subject="manager.desired.ipm.user.>",
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
            "user controller started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main(argv: Sequence[str] = ()) -> None:
    start_role(
        "controller",
        UserControllerSettings,
        missing_required,
        run,
        cli_args=argv or sys.argv[1:],
    )


if __name__ == "__main__":
    main()
