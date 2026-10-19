"""Entrypoint do Manager de `sum.service` (`sum-service-manager`, decisões 0015 e 0033).

Consome `requested` e escreve no SSOT; só insere no outbox. A publicação do outbox é do Publisher,
que é outro processo. Só inicializa e encerra: valida a configuração, abre as conexões e roda o
consumer.
"""

import asyncio
import logging

from sum_service.common.database import open_pool
from sum_service.common.http.health import Health, serve_health
from sum_service.common.lifecycle import (
    InvalidConfigurationError,
    start_role,
    stop_on_signals,
    supervise,
)
from sum_service.common.messaging import connect, jetstream_of
from sum_service.manager.domain.service import CatalogError, parse_catalog
from sum_service.manager.handlers.requested import RequestedHandler
from sum_service.manager.settings import SumServiceManagerSettings, missing_required
from sum_service.manager.transport.requested import Disposition, RequestedConsumer
from sum_service.manager.transport.state import (
    process_account_removed,
    process_observed,
    process_result,
    run_consumer,
)

DURABLE_REQUESTED = "sum-service-manager-requested"
DURABLE_OBSERVED = "sum-service-manager-observed"
DURABLE_COMPLETED = "sum-service-manager-completed"
DURABLE_FAILED = "sum-service-manager-failed"
DURABLE_ACCOUNT_REMOVED = "sum-service-manager-account-removed"

logger = logging.getLogger(__name__)


async def run(settings: SumServiceManagerSettings) -> int:
    stop = stop_on_signals()
    health = Health()
    catalog = parse_catalog(settings.catalog.roles or "")
    nats_client = await connect(settings.nats, name="sum-service-manager")
    pool = await open_pool(settings.database)
    health.add_check("nats", lambda: nats_client.is_connected)
    consumer = RequestedConsumer(
        jetstream_of(nats_client),
        pool,
        RequestedHandler(catalog=catalog),
        durable_name=DURABLE_REQUESTED,
        on_cycle=health.beat,
    )
    jetstream = jetstream_of(nats_client)

    async def handle_observed(data: bytes) -> Disposition:
        return await process_observed(pool, data)

    async def handle_completed(data: bytes) -> Disposition:
        return await process_result(pool, data, "completed")

    async def handle_failed(data: bytes) -> Disposition:
        return await process_result(pool, data, "failed")

    async def handle_account_removed(data: bytes) -> Disposition:
        return await process_account_removed(pool, data)

    tasks = {
        "requested": asyncio.create_task(consumer.run(stop)),
        "observed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="OBSERVED",
                durable=DURABLE_OBSERVED,
                handle=handle_observed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "completed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="RESULT",
                durable=DURABLE_COMPLETED,
                handle=handle_completed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "failed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="RESULT",
                durable=DURABLE_FAILED,
                handle=handle_failed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "account_removed": asyncio.create_task(
            run_consumer(
                jetstream,
                stream="UPDATED",
                durable=DURABLE_ACCOUNT_REMOVED,
                handle=handle_account_removed,
                stop=stop,
                on_cycle=health.beat,
            )
        ),
        "health": asyncio.create_task(serve_health(health, settings.health.port, stop)),
    }
    health.mark_started()
    logger.info("sum service manager started")
    exit_code = await supervise(tasks, stop)
    await nats_client.drain()
    await pool.close()
    return exit_code


def validate(settings: SumServiceManagerSettings) -> None:
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main() -> None:
    start_role("manager", SumServiceManagerSettings, missing_required, run, validate=validate)


if __name__ == "__main__":
    main()
