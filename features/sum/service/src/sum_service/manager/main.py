"""Entrypoint do Manager de `sum.service` (`sum-service-manager`, decisões 0015 e 0033).

Consome `requested` e escreve no SSOT; só insere no outbox. A publicação do outbox é do Publisher,
que é outro processo. Só inicializa e encerra: valida a configuração, abre as conexões e roda o
consumer.
"""

import logging
import sys

from sum_service.common.database import open_pool
from sum_service.common.lifecycle import (
    InvalidConfigurationError,
    start_role,
)
from sum_service.common.runtime import role_runtime
from sum_service.common.service_rules import CatalogError, parse_catalog
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
    catalog = parse_catalog(settings.catalog.roles or "")
    async with role_runtime(settings.messaging, name="sum-service-manager") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)

        async def handle_observed(data: bytes) -> Disposition:
            return await process_observed(pool, data)

        async def handle_completed(data: bytes) -> Disposition:
            return await process_result(pool, data, "completed")

        async def handle_failed(data: bytes) -> Disposition:
            return await process_result(pool, data, "failed")

        async def handle_account_removed(data: bytes) -> Disposition:
            return await process_account_removed(pool, data)

        runtime.start(
            "requested",
            RequestedConsumer(
                runtime.stream,
                pool,
                RequestedHandler(catalog=catalog),
                durable_name=DURABLE_REQUESTED,
                on_cycle=runtime.health.beat,
            ).run(runtime.stop),
        )
        # Estado observado e resultados: um consumer durável por fluxo, cada um com o seu handler.
        for name, stream, durable, handle in (
            ("observed", "OBSERVED", DURABLE_OBSERVED, handle_observed),
            ("completed", "RESULT", DURABLE_COMPLETED, handle_completed),
            ("failed", "RESULT", DURABLE_FAILED, handle_failed),
            ("account_removed", "UPDATED", DURABLE_ACCOUNT_REMOVED, handle_account_removed),
        ):
            runtime.start(
                name,
                run_consumer(
                    runtime.stream,
                    stream=stream,
                    durable=durable,
                    handle=handle,
                    stop=runtime.stop,
                    on_cycle=runtime.health.beat,
                ),
            )
        logger.info("sum service manager started")
        return await runtime.serve(health_port=settings.health.port)


def validate(settings: SumServiceManagerSettings) -> None:
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main() -> None:
    start_role(
        "manager",
        SumServiceManagerSettings,
        missing_required,
        run,
        validate=validate,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
