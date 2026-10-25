"""Entrypoint do Executor de Permission (`ipm-permission-executor`, decisões 0015, 0063 e 0083).

Só inicializa e encerra: valida a configuração, conecta ao NATS, abre o cliente de escrita do
Zitadel (`roles-<módulo>`) e roda os consumers de `action`. O Executor não acessa o SSOT.
"""

import logging
import sys

import httpx

from ipm_permission.common.lifecycle import start_role
from ipm_permission.common.messaging import StreamPublisher
from ipm_permission.common.runtime import role_runtime
from ipm_permission.executor.actions.permission_actions import Drivers
from ipm_permission.executor.drivers.project_role import ProjectRoleDriver
from ipm_permission.executor.engine.executor import Executor
from ipm_permission.executor.provider.identity import IdentityConnection
from ipm_permission.executor.settings import PermissionExecutorSettings, missing_required
from ipm_permission.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: PermissionExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-permission-executor") as runtime:
        http_client = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http_client.aclose)
        connection = IdentityConnection(settings.identity, http_client)
        executor = Executor(
            Drivers(project_roles=ProjectRoleDriver(connection)),
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
        logger.info("permission executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("executor", PermissionExecutorSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
