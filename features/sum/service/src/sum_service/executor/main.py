"""Entrypoint do Executor de `sum.service` (`sum-service-executor`, decisões 0015, 0032 e 0033).

Consome uma partição do Stream `ACTION`, executa cada `action` no Zitadel (único componente com
escrita de
roles de serviço) e publica `completed` ou `failed`. Só inicializa e encerra.
"""

import asyncio
import logging

import httpx

from sum_service.common.http.health import Health, serve_health
from sum_service.common.lifecycle import (
    InvalidConfigurationError,
    start_role,
    stop_on_signals,
    supervise,
)
from sum_service.common.messaging import JetStreamPublisher, connect, jetstream_of
from sum_service.common.service_rules import CatalogError, parse_catalog
from sum_service.executor.engine.executor import Executor
from sum_service.executor.provider.zitadel import ZitadelGranter
from sum_service.executor.settings import SumServiceExecutorSettings, missing_required
from sum_service.executor.transport.consumers import PullConsumer
from sum_service.executor.transport.nats import DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: SumServiceExecutorSettings) -> int:
    stop = stop_on_signals()
    catalog = parse_catalog(settings.catalog.roles or "")
    health = Health()
    nats_client = await connect(settings.nats, name="sum-service-executor")
    jetstream = jetstream_of(nats_client)
    health.add_check("nats", lambda: nats_client.is_connected)
    async with httpx.AsyncClient(timeout=settings.zitadel.timeout_seconds) as client:
        granter = ZitadelGranter(settings.zitadel, client)
        executor = Executor(
            granter,
            DirectStateReader(jetstream),
            JetStreamPublisher(jetstream),
            catalog,
        )

        async def handle(data: bytes) -> object:
            return await executor.on_action(data)

        # Um consumer e um laço por partição, como no Executor do User (decisão 0018): uma ação
        # por vez em cada recurso, e até `count` recursos em paralelo.
        tasks = {
            f"action-p{partition}": asyncio.create_task(
                PullConsumer(
                    jetstream,
                    stream="ACTION",
                    durable=f"sum-service-executor-action-p{partition}",
                    handle=handle,
                    on_cycle=health.beat,
                ).run(stop)
            )
            for partition in range(settings.partition.count)
        }
        tasks["health"] = asyncio.create_task(serve_health(health, settings.health.port, stop))
        health.mark_started()
        logger.info(
            "sum service executor started",
            extra={"smarkee.partition.count": settings.partition.count},
        )
        exit_code = await supervise(tasks, stop)
        await nats_client.drain()
    return exit_code


def validate(settings: SumServiceExecutorSettings) -> None:
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main() -> None:
    start_role("executor", SumServiceExecutorSettings, missing_required, run, validate=validate)


if __name__ == "__main__":
    main()
