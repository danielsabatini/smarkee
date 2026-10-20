"""Entrypoint do Observer de `sum.service` (`sum-service-observer`, decisões 0015 e 0033).

Lê o Zitadel só de leitura e publica `observed`. Consome o `desired` (para saber o que observar)
e os resultados (para observar depois de cada ação), e observa periodicamente. Só inicializa e
encerra: cria os consumers de estado da instância, que reconstroem o que observar.
"""

import asyncio
import logging
import random
import sys

import httpx

from sum_service.common.http.health import Health
from sum_service.common.lifecycle import (
    InvalidConfigurationError,
    start_role,
)
from sum_service.common.messaging import (
    StateConsumer,
    StreamPublisher,
    new_instance_name,
)
from sum_service.common.runtime import role_runtime
from sum_service.common.service_rules import CatalogError, parse_catalog
from sum_service.observer.engine.observer import Observer
from sum_service.observer.provider.identity import IdentityReader
from sum_service.observer.settings import (
    LoopSettings,
    SumServiceObserverSettings,
    missing_required,
)
from sum_service.observer.transport.streams import STREAMS

logger = logging.getLogger(__name__)


async def _observe_periodically(
    observer: Observer, settings: LoopSettings, stop: asyncio.Event, health: Health
) -> None:
    """Observa todos os recursos de tempos em tempos, com jitter."""
    while not stop.is_set():
        health.beat()
        jitter = 1 + random.uniform(-settings.observation_jitter, settings.observation_jitter)  # noqa: S311 (jitter, não criptografia)
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.observation_interval_seconds * jitter
            )
        except TimeoutError:
            await observer.observe_all()


async def run(settings: SumServiceObserverSettings) -> int:
    catalog = parse_catalog(settings.catalog.roles or "")
    async with role_runtime(settings.messaging, name="sum-service-observer") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        observer = Observer(
            IdentityReader(settings.identity, http),
            StreamPublisher(runtime.stream),
            catalog,
            partition_index=settings.partition.index,
            partition_count=settings.partition.count,
        )
        instance = new_instance_name()
        for stream, subject, suffix in STREAMS:
            runtime.start(
                suffix,
                StateConsumer(
                    runtime.stream,
                    observer,
                    durable=f"sum-service-observer-{suffix}-{instance}",
                    stream=stream,
                    filter_subject=subject,
                    inactive_threshold_seconds=settings.messaging.consumer_inactive_threshold_seconds,
                    traced=False,
                    on_cycle=runtime.health.beat,
                ).run(runtime.stop),
            )
        runtime.start(
            "periodic",
            _observe_periodically(observer, settings.loop, runtime.stop, runtime.health),
        )
        logger.info(
            "sum service observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        return await runtime.serve(health_port=settings.health.port)


def validate(settings: SumServiceObserverSettings) -> None:
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main() -> None:
    start_role(
        "observer",
        SumServiceObserverSettings,
        missing_required,
        run,
        validate=validate,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
