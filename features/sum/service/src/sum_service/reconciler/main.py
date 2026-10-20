"""Entrypoint do Reconciler de `sum.service` (`sum-service-reconciler`, decisões 0015 e 0033).

Consome `desired`, `observed` e os resultados (`completed` e `failed`), decide e publica as `action`
no stream `ACTION`. Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os
consumers de estado da instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import logging
import sys

from sum_service.common.lifecycle import start_role
from sum_service.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from sum_service.common.runtime import role_runtime
from sum_service.reconciler.engine.reconciler import Reconciler, periodic_reevaluation
from sum_service.reconciler.settings import SumServiceReconcilerSettings, missing_required
from sum_service.reconciler.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: SumServiceReconcilerSettings) -> int:
    async with role_runtime(settings.messaging, name="sum-service-reconciler") as runtime:
        reconciler = Reconciler(StreamPublisher(runtime.stream), settings.loop)
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    reconciler,
                    durable=f"sum-service-reconciler-{suffix}-{instance}",
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
        logger.info("sum service reconciler started", extra={"smarkee.instance.name": instance})
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "reconciler", SumServiceReconcilerSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
