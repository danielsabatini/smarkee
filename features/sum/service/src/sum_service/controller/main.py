"""Entrypoint do Controller de `sum.service` (`sum-service-controller`, decisões 0033 e 0096).

Unifica observação, decisão pura e execução idempotente com padrão Informer + Workqueue. Na
partida, faz o rollout do catálogo (decisão 0079) antes de abrir os consumers.
"""

import logging
import sys
from collections.abc import Sequence

import httpx

from sum_service.common.database import open_pool
from sum_service.common.lifecycle import InvalidConfigurationError, start_role
from sum_service.common.messaging import StateConsumer, new_instance_name
from sum_service.common.runtime import role_runtime
from sum_service.common.service_rules import CatalogError, parse_catalog
from sum_service.controller.drivers.authorization import AuthorizationDriver
from sum_service.controller.drivers.identity import IdentityConnection
from sum_service.controller.drivers.user import UserDriver
from sum_service.controller.engine.account_removed import (
    ACCOUNT_UPDATED_SUBJECT,
    AccountRemovedHandler,
)
from sum_service.controller.engine.catalog_rollout import roll_out_catalog
from sum_service.controller.engine.controller import ControllerDrivers, ServiceController
from sum_service.controller.settings import SumServiceControllerSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: SumServiceControllerSettings) -> int:
    catalog = parse_catalog(settings.catalog.permissions or "")
    instance = new_instance_name()

    async with (
        role_runtime(settings.messaging, name=f"sum-service-controller-{instance}") as runtime,
        httpx.AsyncClient(timeout=settings.identity.timeout_seconds) as client,
    ):
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        # Antes dos consumers: as ligações passam a acompanhar o catálogo de agora (decisão 0079).
        await roll_out_catalog(pool, catalog)

        connection = IdentityConnection(settings.identity, client)
        drivers = ControllerDrivers(
            users=UserDriver(connection),
            authorizations=AuthorizationDriver(connection, settings.identity),
        )

        controller = ServiceController(pool, drivers, settings)
        runtime.close_after(controller.shutdown)

        # Informer do stream DESIRED: um consumer por instância reconstrói o estado completo na
        # partida.
        consumer = StateConsumer(
            runtime.stream,
            controller,
            durable=f"sum-service-controller-desired-{instance}",
            stream="DESIRED",
            filter_subject="manager.desired.sum.service.>",
            inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("desired", consumer.run(runtime.stop))

        # Conta removida: o SUM apaga as ligações do dono (decisão 0044).
        removed = StateConsumer(
            runtime.stream,
            AccountRemovedHandler(pool),
            durable=f"sum-service-controller-account-removed-{instance}",
            stream="UPDATED",
            filter_subject=ACCOUNT_UPDATED_SUBJECT,
            inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("account-removed", removed.run(runtime.stop))

        for worker_id in range(settings.loop.workers):
            runtime.start(f"worker-{worker_id}", controller.run_worker(worker_id))

        runtime.start("periodic", controller.run_periodic_reevaluation())

        logger.info(
            "service controller started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def validate(settings: SumServiceControllerSettings) -> None:
    try:
        parse_catalog(settings.catalog.permissions or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main(argv: Sequence[str] = ()) -> None:
    start_role(
        "controller",
        SumServiceControllerSettings,
        missing_required,
        run,
        validate=validate,
        cli_args=argv or sys.argv[1:],
    )


if __name__ == "__main__":
    main()
