"""Entrypoint do Observer de Permission (`ipm-permission-observer`, decisões 0015, 0063 e 0083).

Só inicializa e encerra: valida a configuração, conecta ao NATS, abre o cliente somente leitura do
Zitadel e roda os consumers de estado e a observação periódica. Não acessa o SSOT.
"""

import logging
import sys

import httpx

from ipm_permission.common.lifecycle import start_role
from ipm_permission.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_permission.common.runtime import role_runtime
from ipm_permission.observer.domain.observation import Drivers
from ipm_permission.observer.drivers.project_role import ProjectRoleDriver
from ipm_permission.observer.engine.observer import Observer, periodic_observation
from ipm_permission.observer.provider.identity import IdentityConnection
from ipm_permission.observer.settings import PermissionObserverSettings, missing_required
from ipm_permission.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: PermissionObserverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-permission-observer") as runtime:
        http_client = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http_client.aclose)
        connection = IdentityConnection(settings.identity, http_client)
        drivers = Drivers(project_roles=ProjectRoleDriver(connection))
        observer = Observer(drivers, StreamPublisher(runtime.stream), settings)
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    observer,
                    durable=f"ipm-permission-observer-{suffix}-{instance}",
                    stream=stream,
                    filter_subject=subject,
                    inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
                    traced=False,
                    on_cycle=runtime.health.beat,
                ).run(runtime.stop),
            )
        runtime.start(
            "periodic",
            periodic_observation(observer, settings, runtime.stop, on_cycle=runtime.health.beat),
        )
        logger.info(
            "permission observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("observer", PermissionObserverSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
