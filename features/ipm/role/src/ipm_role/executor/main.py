"""Entrypoint do Executor de Role (`ipm-role-executor`, decisões 0015, 0063 e 0083).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com escrita no armazenamento de estado do recurso.
"""

import logging
import sys

from ipm_role.common.lifecycle import start_role
from ipm_role.common.messaging import StreamPublisher
from ipm_role.common.runtime import role_runtime
from ipm_role.executor.actions.role_actions import Drivers
from ipm_role.executor.drivers.role import RoleDriver
from ipm_role.executor.engine.executor import Executor
from ipm_role.executor.provider.storage import StateStoreConnection
from ipm_role.executor.settings import RoleExecutorSettings, missing_required
from ipm_role.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: RoleExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-role-executor") as runtime:
        connection = StateStoreConnection(settings.storage)
        executor = Executor(
            Drivers(roles=RoleDriver(connection)),
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
        logger.info("role executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("executor", RoleExecutorSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
