"""Entrypoint do Observer de Service Account (`ipm-serviceaccount-observer`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a observação periódica. O Observer não acessa o SSOT e só lê o Zitadel.

Os logs do Observer não carregam o `traceparent` das mensagens que ele consome: a observação é
periódica e não consequência de uma requisição (`traced=False`, decisão 0055).
"""

import logging
import sys

import httpx

from ipm_serviceaccount.common.lifecycle import start_role
from ipm_serviceaccount.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_serviceaccount.common.runtime import role_runtime
from ipm_serviceaccount.observer.domain.observation import Drivers
from ipm_serviceaccount.observer.drivers.authorization import AuthorizationDriver
from ipm_serviceaccount.observer.drivers.metadata import MetadataDriver
from ipm_serviceaccount.observer.drivers.serviceaccount import ServiceAccountDriver
from ipm_serviceaccount.observer.engine.observer import Observer, periodic_observation
from ipm_serviceaccount.observer.provider.identity import IdentityConnection
from ipm_serviceaccount.observer.settings import ServiceaccountObserverSettings, missing_required
from ipm_serviceaccount.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: ServiceaccountObserverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-serviceaccount-observer") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        connection = IdentityConnection(settings.identity, http)
        observer = Observer(
            Drivers(
                machines=ServiceAccountDriver(connection),
                authorizations=AuthorizationDriver(connection, settings.identity),
                metadata=MetadataDriver(connection, "users"),
            ),
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
                    durable=f"ipm-serviceaccount-observer-{suffix}-{instance}",
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
            "serviceaccount observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "observer", ServiceaccountObserverSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
