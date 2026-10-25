"""Entrypoint do Reconciler de Permission (`ipm-permission-reconciler`, decisões 0015, 0063 e 0083).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import logging
import sys

from ipm_permission.common.lifecycle import start_role
from ipm_permission.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_permission.common.runtime import role_runtime
from ipm_permission.reconciler.engine.reconciler import Reconciler, periodic_reevaluation
from ipm_permission.reconciler.settings import PermissionReconcilerSettings, missing_required
from ipm_permission.reconciler.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: PermissionReconcilerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-permission-reconciler") as runtime:
        reconciler = Reconciler(StreamPublisher(runtime.stream), settings.loop)
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    reconciler,
                    durable=f"ipm-permission-reconciler-{suffix}-{instance}",
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
        logger.info("permission reconciler started", extra={"smarkee.instance.name": instance})
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "reconciler",
        PermissionReconcilerSettings,
        missing_required,
        run,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
