"""Entrypoint do Executor de Grupo (`ipm-group-executor`, decisões 0015, 0063, 0086 e 0088).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com escrita no estado do recurso, no banco `platform`.
"""

import logging
import sys

from ipm_group.common.database import open_pool
from ipm_group.common.lifecycle import start_role
from ipm_group.common.messaging import StreamPublisher
from ipm_group.common.runtime import role_runtime
from ipm_group.executor.actions.group_actions import Drivers
from ipm_group.executor.drivers.group import GroupDriver
from ipm_group.executor.engine.executor import Executor
from ipm_group.executor.provider.storage import StateStoreConnection
from ipm_group.executor.settings import GroupExecutorSettings, missing_required
from ipm_group.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: GroupExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-group-executor") as runtime:
        pool = await open_pool(settings.database)
        runtime.close_after(pool.close)
        connection = StateStoreConnection(pool)
        executor = Executor(
            Drivers(groups=GroupDriver(connection)),
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
        logger.info("group executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("executor", GroupExecutorSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
