"""Entrypoint do Executor de Account (`core-account-executor`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import logging
import sys

import httpx

from core_account.common.lifecycle import start_role
from core_account.common.messaging import StreamPublisher
from core_account.common.runtime import role_runtime
from core_account.executor.engine.executor import Executor
from core_account.executor.provider.identity import IdentityWriter
from core_account.executor.settings import AccountExecutorSettings, missing_required
from core_account.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: AccountExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="core-account-executor") as runtime:
        http = httpx.AsyncClient(timeout=settings.identity.timeout_seconds)
        runtime.close_after(http.aclose)
        executor = Executor(
            IdentityWriter(settings.identity, http),
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
        logger.info("account executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("executor", AccountExecutorSettings, missing_required, run, cli_args=sys.argv[1:])


if __name__ == "__main__":
    main()
