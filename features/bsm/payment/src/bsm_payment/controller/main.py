"""Entrypoint do Controller de Payment (`bsm-payment-controller`, decisão 0096).

Unifica observação, decisão pura e execução idempotente com padrão Informer + Workqueue.
"""

import logging
import sys

import httpx

from bsm_payment.common.database import open_pool
from bsm_payment.common.dependents import (
    BILLING_ACCOUNT_SUBJECT,
    BillingAccountUsageProjection,
)
from bsm_payment.common.lifecycle import start_role
from bsm_payment.common.messaging import StateConsumer, new_instance_name
from bsm_payment.common.runtime import role_runtime
from bsm_payment.controller.drivers.mercadopago.client import MercadoPagoHttpClient
from bsm_payment.controller.drivers.mercadopago.driver import MercadoPagoDriver
from bsm_payment.controller.drivers.registry import DriverRegistry
from bsm_payment.controller.engine.controller import PaymentController
from bsm_payment.controller.settings import PaymentControllerSettings, missing_required

logger = logging.getLogger(__name__)


async def run(settings: PaymentControllerSettings) -> int:
    instance = new_instance_name()
    async with (
        role_runtime(
            settings.messaging,
            name="bsm-payment-controller",
        ) as runtime,
        httpx.AsyncClient(timeout=settings.mercadopago.timeout_seconds) as mp_http,
    ):
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        billing_accounts = BillingAccountUsageProjection()
        billing_account_consumer = StateConsumer(
            runtime.stream,
            billing_accounts,
            durable=f"bsm-payment-controller-accounts-{instance}",
            stream="DESIRED",
            filter_subject=BILLING_ACCOUNT_SUBJECT,
            inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
            traced=False,
            on_cycle=runtime.health.beat,
        )
        runtime.start("billing-accounts", billing_account_consumer.run(runtime.stop))

        mp_client = MercadoPagoHttpClient(
            base_url=settings.mercadopago.base_url,
            access_token=settings.mercadopago.access_token,
            client=mp_http,
        )
        drivers = DriverRegistry(
            [
                MercadoPagoDriver(
                    mp_client,
                    simulation_mode=settings.mercadopago.simulation_mode,
                )
            ]
        )
        controller = PaymentController(
            pool,
            drivers,
            billing_accounts=billing_accounts,
            partition=settings.partition,
            loop_settings=settings.loop,
        )
        informer = StateConsumer(
            runtime.stream,
            controller,
            durable=f"bsm-payment-controller-desired-{instance}",
            stream="DESIRED",
            filter_subject="desired.bsm.payment.>",
            inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
            traced=False,
            on_cycle=runtime.health.beat,
        )

        runtime.start("informer", informer.run(runtime.stop))
        runtime.start("workers", controller.run_workers(runtime.stop))
        runtime.start("resync", controller.run_periodic_resync(runtime.stop))

        logger.info(
            "payment controller started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "controller",
        PaymentControllerSettings,
        missing_required,
        run,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
