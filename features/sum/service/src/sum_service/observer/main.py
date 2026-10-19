"""Entrypoint do Observer de `sum.service` (`sum-service-observer`, decisões 0015 e 0033).

Lê o Zitadel só de leitura e publica `observed`. Consome o `desired` (para saber o que observar)
e os resultados (para observar depois de cada ação), e observa periodicamente. Só inicializa e
encerra: cria os consumers de estado da instância, que reconstroem o que observar.
"""

import asyncio
import logging
import random

import httpx

from sum_service.common.http.health import Health, serve_health
from sum_service.common.lifecycle import (
    InvalidConfigurationError,
    start_role,
    stop_on_signals,
    supervise,
)
from sum_service.common.messaging import (
    StateConsumer,
    StreamPublisher,
    connect,
    new_instance_name,
    stream_of,
)
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
    stop = stop_on_signals()
    catalog = parse_catalog(settings.catalog.roles or "")
    health = Health()
    messaging_client = await connect(settings.nats, name="sum-service-observer")
    jetstream = stream_of(messaging_client)
    health.add_check("nats", lambda: messaging_client.is_connected)
    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as client:
        reader = IdentityReader(settings.zitadel, client)
        observer = Observer(
            reader,
            StreamPublisher(jetstream),
            catalog,
            partition_index=settings.partition.index,
            partition_count=settings.partition.count,
        )
        instance = new_instance_name()
        tasks = {
            suffix: asyncio.create_task(
                StateConsumer(
                    jetstream,
                    observer,
                    durable=f"sum-service-observer-{suffix}-{instance}",
                    stream=stream,
                    filter_subject=subject,
                    inactive_threshold_seconds=settings.nats.consumer_inactive_threshold_seconds,
                    traced=False,
                    on_cycle=health.beat,
                ).run(stop)
            )
            for stream, subject, suffix in STREAMS
        }
        tasks["periodic"] = asyncio.create_task(
            _observe_periodically(observer, settings.loop, stop, health)
        )
        tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
        health.mark_started()
        logger.info(
            "sum service observer started",
            extra={
                "smarkee.instance.name": instance,
                "smarkee.partition": f"{settings.partition.index}/{settings.partition.count}",
            },
        )
        exit_code = await supervise(tasks, stop)
        await messaging_client.drain()
    return exit_code


def validate(settings: SumServiceObserverSettings) -> None:
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main() -> None:
    start_role("observer", SumServiceObserverSettings, missing_required, run, validate=validate)


if __name__ == "__main__":
    main()
