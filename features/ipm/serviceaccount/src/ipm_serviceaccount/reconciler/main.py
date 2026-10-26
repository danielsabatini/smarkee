"""Entrypoint do Reconciler de Service Account (`ipm-serviceaccount-reconciler`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import logging
import sys

from ipm_serviceaccount.common.lifecycle import start_role
from ipm_serviceaccount.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_serviceaccount.common.runtime import role_runtime
from ipm_serviceaccount.reconciler.engine.reconciler import Reconciler, periodic_reevaluation
from ipm_serviceaccount.reconciler.settings import (
    ServiceaccountReconcilerSettings,
    missing_required,
)
from ipm_serviceaccount.reconciler.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: ServiceaccountReconcilerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-serviceaccount-reconciler") as runtime:
        reconciler = Reconciler(StreamPublisher(runtime.stream), settings.loop)
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    reconciler,
                    durable=f"ipm-serviceaccount-reconciler-{suffix}-{instance}",
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
        logger.info("serviceaccount reconciler started", extra={"smarkee.instance.name": instance})
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "reconciler", ServiceaccountReconcilerSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
