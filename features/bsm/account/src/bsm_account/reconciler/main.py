"""Entrypoint do Reconciler de Billing Account (`bsm-account-reconciler`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import logging
import sys

from bsm_account.common.lifecycle import start_role
from bsm_account.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from bsm_account.common.runtime import role_runtime
from bsm_account.reconciler.engine.reconciler import Reconciler, periodic_reevaluation
from bsm_account.reconciler.settings import AccountReconcilerSettings, missing_required
from bsm_account.reconciler.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: AccountReconcilerSettings) -> int:
    async with role_runtime(settings.messaging, name="bsm-account-reconciler") as runtime:
        reconciler = Reconciler(StreamPublisher(runtime.stream), settings.loop)
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    reconciler,
                    durable=f"bsm-account-reconciler-{suffix}-{instance}",
                    stream=stream,
                    filter_subject=subject,
                    inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
                    traced=True,
                    on_cycle=runtime.health.beat,
                ).run(runtime.stop),
            )
        runtime.start(
            "periodic",
            periodic_reevaluation(
                reconciler, settings.loop, runtime.stop, on_cycle=runtime.health.beat
            ),
        )
        logger.info("account reconciler started", extra={"smarkee.instance.name": instance})
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "reconciler", AccountReconcilerSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
