"""Entrypoint do Executor de `sum.service` (`sum-service-executor`, decisões 0015, 0032 e 0033).

Consome uma partição do Stream `ACTION`, executa cada `action` no Zitadel (único componente com
escrita de
roles de serviço) e publica `completed` ou `failed`. Só inicializa e encerra.
"""

import logging
import sys

import httpx

from sum_service.common.lifecycle import (
    InvalidConfigurationError,
    start_role,
)
from sum_service.common.messaging import StreamPublisher
from sum_service.common.runtime import role_runtime
from sum_service.common.service_rules import CatalogError, parse_catalog
from sum_service.executor.engine.executor import Executor
from sum_service.executor.provider.identity import IdentityGranter
from sum_service.executor.settings import SumServiceExecutorSettings, missing_required
from sum_service.executor.transport.consumers import PullConsumer
from sum_service.executor.transport.messaging import DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: SumServiceExecutorSettings) -> int:
    catalog = parse_catalog(settings.catalog.roles or "")
    async with role_runtime(settings.messaging, name="sum-service-executor") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        executor = Executor(
            IdentityGranter(settings.identity, http),
            DirectStateReader(runtime.stream),
            StreamPublisher(runtime.stream),
            catalog,
        )

        async def handle(data: bytes) -> object:
            return await executor.on_action(data)

        # Um consumer e um laço por partição, como no Executor do User (decisão 0018): uma ação
        # por vez em cada recurso, e até `count` recursos em paralelo.
        for partition in range(settings.partition.count):
            runtime.start(
                f"action-p{partition}",
                PullConsumer(
                    runtime.stream,
                    stream="ACTION",
                    durable=f"sum-service-executor-action-p{partition}",
                    handle=handle,
                    on_cycle=runtime.health.beat,
                ).run(runtime.stop),
            )
        logger.info(
            "sum service executor started",
            extra={"smarkee.partition.count": settings.partition.count},
        )
        return await runtime.serve(health_port=settings.health.port)


def validate(settings: SumServiceExecutorSettings) -> None:
    try:
        parse_catalog(settings.catalog.roles or "")
    except CatalogError as error:
        raise InvalidConfigurationError(f"invalid service catalog: {error}") from None


def main() -> None:
    start_role(
        "executor",
        SumServiceExecutorSettings,
        missing_required,
        run,
        validate=validate,
        cli_args=sys.argv[1:],
    )


if __name__ == "__main__":
    main()
