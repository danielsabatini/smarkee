"""Entrypoint do Controller de Account (`core-account-controller`, decisão 0096).

Unifica observação, decisão pura e execução idempotente com padrão Informer + Workqueue.
"""

import logging
import sys
from collections.abc import Sequence

import httpx

from core_account.common.database import open_pool
from core_account.common.lifecycle import start_role
from core_account.common.messaging import StateConsumer, new_instance_name
from core_account.common.runtime import role_runtime
from core_account.controller.drivers.authorization import AuthorizationDriver
from core_account.controller.drivers.identity import IdentityConnection
from core_account.controller.drivers.metadata import MetadataDriver
from core_account.controller.drivers.user import UserDriver
from core_account.controller.engine.controller import AccountController, ControllerDrivers
from core_account.controller.settings import AccountControllerSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: AccountControllerSettings) -> int:
    instance = new_instance_name()

    async with (
        role_runtime(settings.messaging, name=f"core-account-controller-{instance}") as runtime,
        httpx.AsyncClient(timeout=settings.identity.timeout_seconds) as client,
    ):
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        connection = IdentityConnection(settings.identity, client)
        drivers = ControllerDrivers(
            users=UserDriver(connection, settings.identity),
            authorizations=AuthorizationDriver(connection, settings.identity),
            metadata=MetadataDriver(connection),
        )

        controller = AccountController(pool, drivers, settings)
        runtime.close_after(controller.shutdown)

        # Informer do stream DESIRED: um consumer por instância reconstrói o estado completo na
        # partida.
        consumer = StateConsumer(
            runtime.stream,
            controller,
            durable=f"core-account-controller-desired-{instance}",
            stream="DESIRED",
            filter_subject="desired.core.account.>",
            inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("desired", consumer.run(runtime.stop))

        for worker_id in range(settings.loop.workers):
            runtime.start(f"worker-{worker_id}", controller.run_worker(worker_id))

        runtime.start("periodic", controller.run_periodic_reevaluation())

        logger.info(
            "account controller started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main(argv: Sequence[str] = ()) -> None:
    start_role(
        "controller",
        AccountControllerSettings,
        missing_required,
        run,
        cli_args=argv or sys.argv[1:],
    )


if __name__ == "__main__":
    main()
