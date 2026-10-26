"""Entrypoint do Executor de Service Account (`ipm-serviceaccount-executor`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import logging
import sys

import httpx

from ipm_serviceaccount.common.lifecycle import start_role
from ipm_serviceaccount.common.messaging import StreamPublisher
from ipm_serviceaccount.common.runtime import role_runtime
from ipm_serviceaccount.executor.actions.serviceaccount_actions import Drivers
from ipm_serviceaccount.executor.drivers.authorization import AuthorizationDriver
from ipm_serviceaccount.executor.drivers.metadata import MetadataDriver
from ipm_serviceaccount.executor.drivers.metadata_reader import MetadataReader
from ipm_serviceaccount.executor.drivers.serviceaccount import ServiceAccountDriver
from ipm_serviceaccount.executor.engine.executor import Executor
from ipm_serviceaccount.executor.provider.identity import IdentityConnection
from ipm_serviceaccount.executor.settings import ServiceaccountExecutorSettings, missing_required
from ipm_serviceaccount.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: ServiceaccountExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-serviceaccount-executor") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        connection = IdentityConnection(settings.identity, http)
        executor = Executor(
            Drivers(
                machines=ServiceAccountDriver(connection),
                authorizations=AuthorizationDriver(connection, settings.identity),
                metadata=MetadataDriver(connection, "users"),
                metadata_reader=MetadataReader(connection),
            ),
            StreamPublisher(runtime.stream),
            DirectStateReader(runtime.stream),
        )
        for partition in range(settings.partition.count):
            runtime.start(
                f"action-p{partition}",
                ActionConsumer(
                    runtime.stream, executor, partition=partition, on_cycle=runtime.health.beat
                ).run(runtime.stop),
            )
        logger.info("serviceaccount executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role(
        "executor", ServiceaccountExecutorSettings, missing_required, run, cli_args=sys.argv[1:]
    )


if __name__ == "__main__":
    main()
