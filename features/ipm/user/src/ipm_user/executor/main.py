"""Entrypoint do Executor de User (`ipm-user-executor`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import logging
import sys

import httpx

from ipm_user.common.lifecycle import start_role
from ipm_user.common.messaging import StreamPublisher
from ipm_user.common.runtime import role_runtime
from ipm_user.executor.actions.user_actions import Drivers
from ipm_user.executor.drivers.authorization import AuthorizationDriver
from ipm_user.executor.drivers.metadata import MetadataDriver
from ipm_user.executor.drivers.user import UserDriver
from ipm_user.executor.engine.executor import Executor
from ipm_user.executor.provider.identity import IdentityConnection
from ipm_user.executor.settings import UserExecutorSettings, missing_required
from ipm_user.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: UserExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-user-executor") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        connection = IdentityConnection(settings.identity, http)
        executor = Executor(
            Drivers(
                users=UserDriver(connection),
                authorizations=AuthorizationDriver(connection, settings.identity),
                metadata=MetadataDriver(connection, "users"),
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
        logger.info("user executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("executor", UserExecutorSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
