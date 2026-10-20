"""Entrypoint do Observer de Organization (`ipm-organization-observer`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS, cria os consumers de estado da
instância e roda a observação periódica. O Observer não acessa o SSOT e só lê o Zitadel.

Os logs do Observer não carregam o `traceparent` das mensagens que ele consome: a observação é
periódica e não consequência de uma requisição (`traced=False`, decisão 0055).
"""

import logging
import sys

import httpx

from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from ipm_organization.common.runtime import role_runtime
from ipm_organization.observer.engine.observer import Observer, periodic_observation
from ipm_organization.observer.provider.identity import IdentityReader
from ipm_organization.observer.settings import OrganizationObserverSettings, missing_required
from ipm_organization.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def run(settings: OrganizationObserverSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-organization-observer") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        observer = Observer(
            IdentityReader(settings.identity, http), StreamPublisher(runtime.stream), settings
        )
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    observer,
                    durable=f"ipm-organization-observer-{suffix}-{instance}",
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
            "organization observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "observer", OrganizationObserverSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
