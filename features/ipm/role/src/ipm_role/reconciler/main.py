"""Entrypoint do Reconciler de Role (`ipm-role-reconciler`, decisões 0015, 0063 e 0083).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a reavaliação periódica. O Reconciler não acessa o SSOT.
"""

import logging
import sys

from ipm_role.common.lifecycle import start_role
from ipm_role.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_role.common.runtime import role_runtime
from ipm_role.reconciler.engine.reconciler import Reconciler, periodic_reevaluation
from ipm_role.reconciler.settings import RoleReconcilerSettings, missing_required
from ipm_role.reconciler.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: RoleReconcilerSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-role-reconciler") as runtime:
        reconciler = Reconciler(StreamPublisher(runtime.stream), settings.loop)
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    reconciler,
                    durable=f"ipm-role-reconciler-{suffix}-{instance}",
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
        logger.info("role reconciler started", extra={"smarkee.instance.name": instance})
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("reconciler", RoleReconcilerSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
