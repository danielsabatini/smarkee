"""Entrypoint do Observer de Role (`ipm-role-observer`, decisões 0015, 0063 e 0083).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a observação periódica. O Observer não acessa o SSOT e só lê o estado do recurso no banco `platform`, de
estado do recurso.

Os logs do Observer não carregam o `traceparent` das mensagens que ele consome: a observação é
periódica e não consequência de uma requisição (`traced=False`, decisão 0055).
"""

import logging
import sys

from ipm_role.common.database import open_pool
from ipm_role.common.lifecycle import start_role
from ipm_role.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_role.common.runtime import role_runtime
from ipm_role.observer.domain.observation import Drivers
from ipm_role.observer.drivers.role import RoleDriver
from ipm_role.observer.engine.observer import Observer, periodic_observation
from ipm_role.observer.provider.storage import StateStoreConnection
from ipm_role.observer.settings import RoleObserverSettings, missing_required
from ipm_role.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: RoleObserverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-role-observer") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        connection = StateStoreConnection(pool)
        observer = Observer(
            Drivers(roles=RoleDriver(connection)),
            StreamPublisher(runtime.stream),
            settings,
        )
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    observer,
                    durable=f"ipm-role-observer-{suffix}-{instance}",
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
            "role observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("observer", RoleObserverSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
