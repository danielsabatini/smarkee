"""Entrypoint do Executor de Organization (`ipm-organization-executor`, decisões 0015 e 0063).

Só inicializa e encerra: valida a configuração, conecta ao NATS e roda o consumer de `action`.
O Executor não acessa o SSOT; é o único com credencial de escrita no Zitadel.
"""

import logging

import httpx

from ipm_organization.common.lifecycle import start_role
from ipm_organization.common.messaging import StreamPublisher
from ipm_organization.common.runtime import role_runtime
from ipm_organization.executor.engine.executor import Executor
from ipm_organization.executor.provider.identity import IdentityWriter
from ipm_organization.executor.settings import OrganizationExecutorSettings, missing_required
from ipm_organization.executor.transport.messaging import ActionConsumer, DirectStateReader

logger = logging.getLogger(__name__)


async def run(settings: OrganizationExecutorSettings) -> int:
    async with role_runtime(settings.messaging, name="ipm-organization-executor") as runtime:
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
        logger.info("organization executor started")
        return await runtime.serve(health_port=settings.health.port)


def main() -> None:
    start_role("executor", OrganizationExecutorSettings, missing_required, run)


if __name__ == "__main__":
    main()
